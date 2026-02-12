"""
Maildir Parser for Email Sensor
Parses RFC 5322 email messages from Maildir format
"""

import email
import hashlib
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from email import policy
from email.message import EmailMessage
from email.utils import parsedate_to_datetime, parseaddr
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Generator

logger = logging.getLogger(__name__)


class MaildirParser:
    """
    Parse emails from Maildir format (as synced by mbsync).

    Maildir structure:
    ~/Mail/Gmail/
    ├── INBOX/
    │   ├── cur/  (read emails)
    │   ├── new/  (unread emails)
    │   └── tmp/  (in-transit)
    ├── [Gmail]/
    │   ├── Sent Mail/
    │   ├── Drafts/
    │   └── ...
    └── Other folders/
    """

    def __init__(
        self,
        base_path: str,
        exclude_folders: Optional[List[str]] = None,
        exclude_categories: Optional[List[str]] = None,
        max_age_years: int = 5,
        min_body_length: int = 50,
        max_email_size: int = 10 * 1024 * 1024,  # 10MB
    ):
        """
        Initialize Maildir parser.

        Args:
            base_path: Path to Maildir root (e.g., ~/Mail/Gmail)
            exclude_folders: Folder names to skip
            exclude_categories: Gmail categories to skip
            max_age_years: Only process emails from past N years
            min_body_length: Minimum body length to process
            max_email_size: Maximum email file size to process
        """
        self.base_path = Path(base_path).expanduser()
        self.exclude_folders = set(exclude_folders or [
            "[Gmail]/Spam",
            "[Gmail]/Trash",
            "Deleted Messages",
        ])
        self.exclude_categories = set(c.lower() for c in (exclude_categories or [
            "promotions",
            "social",
            "updates",
            "forums",
        ]))
        self.max_age_years = max_age_years
        self.min_body_length = min_body_length
        self.max_email_size = max_email_size

        # Compute cutoff date
        self.cutoff_date = datetime.now(timezone.utc) - timedelta(days=365 * max_age_years)

        logger.info(f"Maildir parser initialized: {self.base_path}")
        logger.info(f"Date cutoff: {self.cutoff_date.isoformat()}")

    def discover_folders(self) -> List[Path]:
        """
        Discover all Maildir folders in the base path.

        Returns:
            List of folder paths that contain cur/ and new/ subdirs
        """
        folders = []

        if not self.base_path.exists():
            logger.error(f"Maildir base path does not exist: {self.base_path}")
            return folders

        for root, dirs, files in os.walk(self.base_path):
            root_path = Path(root)

            # Check if this is a Maildir folder (has cur/ and new/)
            if (root_path / "cur").is_dir() and (root_path / "new").is_dir():
                # Get relative path for folder name matching
                rel_path = root_path.relative_to(self.base_path)
                folder_name = str(rel_path)

                # Check exclusions
                if self._should_exclude_folder(folder_name):
                    logger.debug(f"Excluding folder: {folder_name}")
                    continue

                folders.append(root_path)
                logger.debug(f"Found Maildir folder: {folder_name}")

        logger.info(f"Discovered {len(folders)} Maildir folders")
        return folders

    def _should_exclude_folder(self, folder_name: str) -> bool:
        """Check if folder should be excluded."""
        # Check exact matches
        if folder_name in self.exclude_folders:
            return True

        # Check prefix matches (e.g., "[Gmail]/Spam" matches "[Gmail]/Spam/subfolder")
        for excluded in self.exclude_folders:
            if folder_name.startswith(excluded):
                return True

        return False

    def scan_folder(self, folder_path: Path) -> Generator[Path, None, None]:
        """
        Scan a Maildir folder for email files.

        Args:
            folder_path: Path to Maildir folder

        Yields:
            Paths to email files
        """
        # Scan cur/ (read emails)
        cur_path = folder_path / "cur"
        if cur_path.exists():
            for email_file in cur_path.iterdir():
                if email_file.is_file() and not email_file.name.startswith('.'):
                    yield email_file

        # Scan new/ (unread emails)
        new_path = folder_path / "new"
        if new_path.exists():
            for email_file in new_path.iterdir():
                if email_file.is_file() and not email_file.name.startswith('.'):
                    yield email_file

    def parse_email(self, email_path: Path) -> Optional[Dict[str, Any]]:
        """
        Parse an email file and extract relevant data.

        Args:
            email_path: Path to email file

        Returns:
            Parsed email data dict or None if should be skipped
        """
        try:
            # Check file size
            file_size = email_path.stat().st_size
            if file_size > self.max_email_size:
                logger.debug(f"Skipping large email ({file_size} bytes): {email_path.name}")
                return None

            # Read and parse email
            with open(email_path, 'rb') as f:
                msg = email.message_from_binary_file(f, policy=policy.default)

            # Extract Message-ID (required for RID)
            message_id = msg.get('Message-ID', '')
            if not message_id:
                # Generate fallback from file path
                message_id = f"<{hashlib.sha256(str(email_path).encode()).hexdigest()[:32]}@local>"
                logger.debug(f"No Message-ID, generated: {message_id}")

            # Normalize Message-ID
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
            from_name, from_email = parseaddr(from_addr)

            to_addrs = self._parse_address_list(msg.get('To', ''))
            cc_addrs = self._parse_address_list(msg.get('Cc', ''))

            subject = msg.get('Subject', '').strip() or '(No Subject)'

            # Extract body
            body_text, body_html = self._extract_body(msg)

            # Use HTML body as fallback if text is too short
            if len(body_text) < self.min_body_length and body_html:
                body_text = self._html_to_text(body_html)

            if len(body_text) < self.min_body_length:
                logger.debug(f"Skipping short email ({len(body_text)} chars): {message_id}")
                return None

            # Extract attachments
            attachments = self._extract_attachments(msg)

            # Get Gmail labels from folder path
            folder_labels = self._get_folder_labels(email_path)

            # Check for excluded categories
            if self._has_excluded_category(folder_labels, msg):
                logger.debug(f"Skipping categorized email: {message_id}")
                return None

            # Compute content hash for change detection
            content_hash = hashlib.sha256(body_text.encode('utf-8')).hexdigest()

            # Get thread ID from references/in-reply-to
            thread_id = self._extract_thread_id(msg)

            return {
                'message_id': message_id,
                'thread_id': thread_id,
                'from_address': from_email,
                'from_name': from_name or from_email.split('@')[0],
                'to_addresses': to_addrs,
                'cc_addresses': cc_addrs,
                'subject': subject,
                'date_sent': date_sent,
                'body_text': body_text,
                'body_html': body_html,
                'attachments': attachments,
                'labels': folder_labels,
                'content_hash': content_hash,
                'file_path': str(email_path),
                'file_size': file_size,
            }

        except Exception as e:
            logger.error(f"Error parsing email {email_path}: {e}")
            return None

    def _parse_date(self, msg: EmailMessage) -> Optional[datetime]:
        """Parse email Date header."""
        date_str = msg.get('Date', '')
        if not date_str:
            return None

        try:
            dt = parsedate_to_datetime(date_str)
            # Ensure timezone-aware
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception as e:
            logger.debug(f"Failed to parse date '{date_str}': {e}")
            return None

    def _parse_address_list(self, addr_string: str) -> List[str]:
        """Parse comma-separated address list."""
        if not addr_string:
            return []

        addresses = []
        # Split by comma but be careful of quoted strings
        for part in addr_string.split(','):
            _, email_addr = parseaddr(part.strip())
            if email_addr:
                addresses.append(email_addr.lower())

        return addresses

    def _extract_body(self, msg: EmailMessage) -> Tuple[str, str]:
        """
        Extract text and HTML body from email.

        Returns:
            Tuple of (text_body, html_body)
        """
        text_body = ""
        html_body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get('Content-Disposition', ''))

                # Skip attachments
                if 'attachment' in content_disposition:
                    continue

                if content_type == 'text/plain' and not text_body:
                    text_body = self._decode_payload(part)
                elif content_type == 'text/html' and not html_body:
                    html_body = self._decode_payload(part)
        else:
            content_type = msg.get_content_type()
            if content_type == 'text/plain':
                text_body = self._decode_payload(msg)
            elif content_type == 'text/html':
                html_body = self._decode_payload(msg)

        return text_body.strip(), html_body.strip()

    def _decode_payload(self, part) -> str:
        """Decode email part payload to string."""
        try:
            payload = part.get_payload(decode=True)
            if payload is None:
                return ""

            # Try to get charset
            charset = part.get_content_charset() or 'utf-8'

            try:
                return payload.decode(charset)
            except (UnicodeDecodeError, LookupError):
                # Fallback to utf-8 with error handling
                return payload.decode('utf-8', errors='replace')

        except Exception as e:
            logger.debug(f"Failed to decode payload: {e}")
            return ""

    def _html_to_text(self, html: str) -> str:
        """Convert HTML to plain text."""
        try:
            # Simple HTML to text conversion
            import re

            # Remove scripts and styles
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)

            # Replace common block elements with newlines
            text = re.sub(r'<(br|p|div|li|tr)[^>]*>', '\n', text, flags=re.IGNORECASE)

            # Remove all remaining tags
            text = re.sub(r'<[^>]+>', '', text)

            # Decode HTML entities
            import html as html_module
            text = html_module.unescape(text)

            # Normalize whitespace
            text = re.sub(r'\n\s*\n', '\n\n', text)
            text = re.sub(r' +', ' ', text)

            return text.strip()

        except Exception as e:
            logger.debug(f"Failed to convert HTML to text: {e}")
            return ""

    def _extract_attachments(self, msg: EmailMessage) -> List[Dict[str, Any]]:
        """Extract attachment metadata from email."""
        attachments = []

        if not msg.is_multipart():
            return attachments

        for idx, part in enumerate(msg.walk()):
            content_disposition = str(part.get('Content-Disposition', ''))

            if 'attachment' not in content_disposition:
                continue

            filename = part.get_filename() or f"attachment_{idx}"
            content_type = part.get_content_type()

            try:
                payload = part.get_payload(decode=True)
                if payload:
                    size = len(payload)
                    content_hash = hashlib.sha256(payload).hexdigest()[:16]
                else:
                    size = 0
                    content_hash = "empty"
            except Exception:
                size = 0
                content_hash = "error"

            attachments.append({
                'index': len(attachments),
                'filename': filename,
                'content_type': content_type,
                'size': size,
                'content_hash': content_hash,
            })

        return attachments

    def _get_folder_labels(self, email_path: Path) -> List[str]:
        """Get folder-based labels from email path."""
        try:
            rel_path = email_path.relative_to(self.base_path)
            # Get folder path (excluding cur/new/tmp)
            parts = rel_path.parts[:-2]  # Remove cur/new and filename
            if parts:
                return ['/'.join(parts)]
            return ['INBOX']
        except Exception:
            return []

    def _has_excluded_category(self, folder_labels: List[str], msg: EmailMessage) -> bool:
        """Check if email belongs to an excluded category."""
        # Check folder-based categories
        for label in folder_labels:
            if label.lower() in self.exclude_categories:
                return True

        # Check X-GM-LABELS header (if present from IMAP)
        gm_labels = msg.get('X-GM-LABELS', '')
        if gm_labels:
            for category in self.exclude_categories:
                if category in gm_labels.lower():
                    return True

        return False

    def _extract_thread_id(self, msg: EmailMessage) -> Optional[str]:
        """Extract thread ID from References or In-Reply-To headers."""
        # Try References first (contains full thread chain)
        references = msg.get('References', '')
        if references:
            # Get first message ID in thread
            match = re.search(r'<[^>]+>', references)
            if match:
                return hashlib.sha256(match.group(0).encode()).hexdigest()[:16]

        # Fall back to In-Reply-To
        in_reply_to = msg.get('In-Reply-To', '')
        if in_reply_to:
            match = re.search(r'<[^>]+>', in_reply_to)
            if match:
                return hashlib.sha256(match.group(0).encode()).hexdigest()[:16]

        # No thread - use Message-ID as thread ID (single-message thread)
        message_id = msg.get('Message-ID', '')
        if message_id:
            return hashlib.sha256(message_id.encode()).hexdigest()[:16]

        return None

    def scan_all(self) -> Generator[Dict[str, Any], None, None]:
        """
        Scan all Maildir folders and yield parsed emails.

        Yields:
            Parsed email data dicts
        """
        folders = self.discover_folders()

        for folder in folders:
            folder_name = folder.relative_to(self.base_path)
            logger.info(f"Scanning folder: {folder_name}")

            count = 0
            for email_path in self.scan_folder(folder):
                parsed = self.parse_email(email_path)
                if parsed:
                    parsed['folder'] = str(folder_name)
                    yield parsed
                    count += 1

            logger.info(f"Processed {count} emails from {folder_name}")
