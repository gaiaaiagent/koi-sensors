"""
Proton Mail IMAP Fetcher for Email Sensor
Connects to Proton Mail Bridge IMAP to fetch emails incrementally by UID.
"""

import email
import hashlib
import imaplib
import logging
import re
import subprocess
import time
from datetime import datetime, timezone, timedelta
from email import policy
from email.utils import parsedate_to_datetime, parseaddr
from typing import Dict, List, Any, Optional, Generator

logger = logging.getLogger(__name__)


class ProtonIMAPFetcher:
    """
    Fetch emails from Proton Mail via Proton Bridge IMAP.

    Outputs dicts in the same shape as MaildirParser.parse_email() so the
    existing EmailSensor.process_email() pipeline works unchanged.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 1143,
        username: str = "",
        password: Optional[str] = None,
        password_cmd: Optional[str] = None,
        folders: Optional[List[str]] = None,
        exclude_folders: Optional[List[str]] = None,
        max_age_years: int = 5,
        min_body_length: int = 50,
        max_email_size: int = 10 * 1024 * 1024,
    ):
        self.host = host
        self.port = port
        self.username = username
        self._password = password
        self._password_cmd = password_cmd
        self.folders = folders or ["INBOX"]
        self.exclude_folders = set(f.upper() for f in (exclude_folders or []))
        self.max_age_years = max_age_years
        self.min_body_length = min_body_length
        self.max_email_size = max_email_size
        self.cutoff_date = datetime.now(timezone.utc) - timedelta(days=365 * max_age_years)
        self._conn: Optional[imaplib.IMAP4_SSL] = None

    def _get_password(self) -> str:
        """Resolve password from direct value or Keychain command."""
        if self._password:
            return self._password
        if self._password_cmd:
            result = subprocess.run(
                self._password_cmd, shell=True,
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                raise RuntimeError(f"Password command failed: {result.stderr.strip()}")
            return result.stdout.strip()
        raise ValueError("No password or password_cmd configured")

    def connect(self, max_retries: int = 3, base_delay: float = 5.0) -> None:
        """Connect to Proton Bridge IMAP with retry (STARTTLS on 1143)."""
        for attempt in range(max_retries):
            try:
                self._conn = imaplib.IMAP4(self.host, self.port)
                self._conn.starttls()
                self._conn.login(self.username, self._get_password())
                logger.info(f"Connected to Proton Bridge IMAP at {self.host}:{self.port}")
                return
            except (ConnectionRefusedError, OSError, imaplib.IMAP4.error) as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"IMAP connect attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    raise ConnectionError(
                        f"Failed to connect to Proton Bridge after {max_retries} attempts. "
                        f"Is Proton Mail Bridge running? ({e})"
                    )

    def disconnect(self) -> None:
        """Clean IMAP logout."""
        if self._conn:
            try:
                self._conn.logout()
            except Exception:
                pass
            self._conn = None

    def get_folder_list(self) -> List[str]:
        """List all IMAP folders from Bridge."""
        if not self._conn:
            raise RuntimeError("Not connected")
        status, data = self._conn.list()
        if status != "OK":
            return []
        folders = []
        for item in data:
            if isinstance(item, bytes):
                # Parse IMAP LIST response: (\\HasNoChildren) "/" "INBOX"
                match = re.search(rb'"([^"]+)"$', item)
                if match:
                    folders.append(match.group(1).decode('utf-8'))
        return folders

    def get_uidvalidity(self, folder: str) -> Optional[int]:
        """Get UIDVALIDITY for a folder (changes if mailbox is rebuilt)."""
        if not self._conn:
            raise RuntimeError("Not connected")
        status, data = self._conn.select(folder, readonly=True)
        if status != "OK":
            return None
        # UIDVALIDITY is returned in untagged responses
        status, uidval_data = self._conn.response("UIDVALIDITY")
        if status == "OK" and uidval_data and uidval_data[0]:
            return int(uidval_data[0])
        return None

    def get_max_uid(self, folder: str) -> int:
        """Get the highest UID in a folder."""
        if not self._conn:
            raise RuntimeError("Not connected")
        status, data = self._conn.select(folder, readonly=True)
        if status != "OK":
            return 0
        # Search for all messages and get the last UID
        status, uids = self._conn.uid("SEARCH", None, "ALL")
        if status != "OK" or not uids[0]:
            return 0
        uid_list = uids[0].split()
        return int(uid_list[-1]) if uid_list else 0

    def fetch_new_emails(
        self, folder: str, since_uid: int = 0
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Fetch emails with UID > since_uid from a folder.

        Uses BODY.PEEK to avoid marking messages as read.

        Yields:
            Dicts in the same shape as MaildirParser.parse_email() output.
        """
        if not self._conn:
            raise RuntimeError("Not connected")

        status, data = self._conn.select(folder, readonly=True)
        if status != "OK":
            logger.error(f"Failed to select folder {folder}: {data}")
            return

        # Search for messages with UID > since_uid
        if since_uid > 0:
            search_criteria = f"{since_uid + 1}:*"
        else:
            search_criteria = "1:*"

        status, uid_data = self._conn.uid("SEARCH", None, "ALL")
        if status != "OK" or not uid_data[0]:
            logger.info(f"No messages in {folder}")
            return

        all_uids = uid_data[0].split()
        new_uids = [uid for uid in all_uids if int(uid) > since_uid]

        if not new_uids:
            logger.info(f"No new messages in {folder} (last UID: {since_uid})")
            return

        logger.info(f"Fetching {len(new_uids)} new messages from {folder}")

        for uid in new_uids:
            try:
                # Fetch with BODY.PEEK to not mark as read
                status, msg_data = self._conn.uid(
                    "FETCH", uid, "(BODY.PEEK[] RFC822.SIZE)"
                )
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue

                # msg_data[0] is a tuple: (envelope, raw_bytes)
                if isinstance(msg_data[0], tuple):
                    raw_bytes = msg_data[0][1]
                    # Extract size from envelope if available
                    envelope = msg_data[0][0]
                    size_match = re.search(rb'RFC822\.SIZE (\d+)', envelope)
                    file_size = int(size_match.group(1)) if size_match else len(raw_bytes)
                else:
                    continue

                if file_size > self.max_email_size:
                    logger.debug(f"Skipping large email UID {uid} ({file_size} bytes)")
                    continue

                parsed = self._parse_message(raw_bytes, folder)
                if parsed:
                    parsed['uid'] = int(uid)
                    yield parsed

            except Exception as e:
                logger.error(f"Error fetching UID {uid} from {folder}: {e}")
                continue

    def _parse_message(
        self, raw_bytes: bytes, folder: str
    ) -> Optional[Dict[str, Any]]:
        """
        Parse raw RFC5322 email bytes into the standard dict format.

        Returns the same shape as MaildirParser.parse_email().
        """
        try:
            msg = email.message_from_bytes(raw_bytes, policy=policy.default)

            # Extract Message-ID
            message_id = msg.get('Message-ID', '')
            if not message_id:
                message_id = f"<{hashlib.sha256(raw_bytes[:256]).hexdigest()[:32]}@proton-local>"
            message_id = message_id.strip()
            if not message_id.startswith('<'):
                message_id = f'<{message_id}'
            if not message_id.endswith('>'):
                message_id = f'{message_id}>'

            # Extract date
            date_sent = self._parse_date(msg)
            if date_sent and date_sent < self.cutoff_date:
                logger.debug(f"Skipping old email ({date_sent}): {message_id}")
                return None

            # Extract headers
            from_addr = msg.get('From', '')
            from_name, from_email_addr = parseaddr(from_addr)

            to_addrs = self._parse_address_list(msg.get('To', ''))
            cc_addrs = self._parse_address_list(msg.get('Cc', ''))

            subject = msg.get('Subject', '').strip() or '(No Subject)'

            # Extract body
            body_text, body_html = self._extract_body(msg)

            # Use HTML as fallback
            if len(body_text) < self.min_body_length and body_html:
                body_text = self._html_to_text(body_html)

            if len(body_text) < self.min_body_length:
                logger.debug(f"Skipping short email ({len(body_text)} chars): {message_id}")
                return None

            # Extract attachments
            attachments = self._extract_attachments(msg)

            # Content hash for change detection
            content_hash = hashlib.sha256(body_text.encode('utf-8')).hexdigest()

            # Thread ID
            thread_id = self._extract_thread_id(msg)

            return {
                'message_id': message_id,
                'thread_id': thread_id,
                'from_address': from_email_addr.lower() if from_email_addr else '',
                'from_name': from_name or (from_email_addr.split('@')[0] if from_email_addr else ''),
                'to_addresses': to_addrs,
                'cc_addresses': cc_addrs,
                'subject': subject,
                'date_sent': date_sent,
                'body_text': body_text,
                'body_html': body_html,
                'attachments': attachments,
                'labels': [folder],
                'content_hash': content_hash,
                'folder': folder,
            }

        except Exception as e:
            logger.error(f"Error parsing IMAP message: {e}")
            return None

    @staticmethod
    def _parse_date(msg) -> Optional[datetime]:
        date_str = msg.get('Date', '')
        if not date_str:
            return None
        try:
            dt = parsedate_to_datetime(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    @staticmethod
    def _parse_address_list(addr_string: str) -> List[str]:
        if not addr_string:
            return []
        addresses = []
        for part in addr_string.split(','):
            _, email_addr = parseaddr(part.strip())
            if email_addr:
                addresses.append(email_addr.lower())
        return addresses

    @staticmethod
    def _extract_body(msg) -> tuple:
        text_body = ""
        html_body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get('Content-Disposition', ''))
                if 'attachment' in disposition:
                    continue
                if content_type == 'text/plain' and not text_body:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or 'utf-8'
                        try:
                            text_body = payload.decode(charset)
                        except (UnicodeDecodeError, LookupError):
                            text_body = payload.decode('utf-8', errors='replace')
                elif content_type == 'text/html' and not html_body:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or 'utf-8'
                        try:
                            html_body = payload.decode(charset)
                        except (UnicodeDecodeError, LookupError):
                            html_body = payload.decode('utf-8', errors='replace')
        else:
            content_type = msg.get_content_type()
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or 'utf-8'
                try:
                    text = payload.decode(charset)
                except (UnicodeDecodeError, LookupError):
                    text = payload.decode('utf-8', errors='replace')
                if content_type == 'text/plain':
                    text_body = text
                elif content_type == 'text/html':
                    html_body = text
        return text_body.strip(), html_body.strip()

    @staticmethod
    def _html_to_text(html: str) -> str:
        try:
            import html as html_module
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<(br|p|div|li|tr)[^>]*>', '\n', text, flags=re.IGNORECASE)
            text = re.sub(r'<[^>]+>', '', text)
            text = html_module.unescape(text)
            text = re.sub(r'\n\s*\n', '\n\n', text)
            text = re.sub(r' +', ' ', text)
            return text.strip()
        except Exception:
            return ""

    @staticmethod
    def _extract_attachments(msg) -> List[Dict[str, Any]]:
        attachments = []
        if not msg.is_multipart():
            return attachments
        for idx, part in enumerate(msg.walk()):
            disposition = str(part.get('Content-Disposition', ''))
            content_type = (part.get_content_type() or '').lower()
            filename = part.get_filename()
            is_calendar = (
                content_type in ('text/calendar', 'application/ics')
                or (content_type == 'application/octet-stream'
                    and filename and filename.lower().endswith('.ics'))
            )
            if 'attachment' not in disposition and not is_calendar:
                continue
            filename = filename or f"attachment_{idx}"
            try:
                payload = part.get_payload(decode=True)
                size = len(payload) if payload else 0
                content_hash = hashlib.sha256(payload).hexdigest()[:16] if payload else "empty"
            except Exception:
                payload = None
                size = 0
                content_hash = "error"
            att = {
                'index': len(attachments),
                'filename': filename,
                'content_type': content_type,
                'size': size,
                'content_hash': content_hash,
            }
            if is_calendar and payload:
                att['ics_payload'] = payload
                att['is_inline_calendar'] = 'attachment' not in (disposition or '')
            attachments.append(att)
        return attachments

    @staticmethod
    def _extract_thread_id(msg) -> Optional[str]:
        references = msg.get('References', '')
        if references:
            match = re.search(r'<[^>]+>', references)
            if match:
                return hashlib.sha256(match.group(0).encode()).hexdigest()[:16]
        in_reply_to = msg.get('In-Reply-To', '')
        if in_reply_to:
            match = re.search(r'<[^>]+>', in_reply_to)
            if match:
                return hashlib.sha256(match.group(0).encode()).hexdigest()[:16]
        message_id = msg.get('Message-ID', '')
        if message_id:
            return hashlib.sha256(message_id.encode()).hexdigest()[:16]
        return None
