"""
KOI Sensor Network - Newsletter Email Sensor

Polls a Gmail (or generic IMAP) account, watches one or more folders/labels
populated by Gmail filters, and emits KOI bundles for each newsletter
email. Per-sender routing maps senders to slug + access_source + tags +
is_private flags.

Designed for paid Substack-style newsletters where the email body contains
the full post, but works equally well for any newsletter delivered by
email.

Credentials live in the koi-sensors root .env (loaded by run-sensor.sh);
config.yaml references them via ${VAR}.
"""

import argparse
import asyncio
import email
import hashlib
import imaplib
import json
import logging
import mailbox
import os
import re
import ssl
from datetime import datetime, timezone, timedelta
from email import policy
from email.utils import parsedate_to_datetime, parseaddr
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import html2text
import yaml

from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.rid_system import RID
from koi_protocol.core.bundle_system import document_to_bundle
from shared.persistent_state import PersistentSensorState


_ENV_VAR_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand_env(value: str) -> str:
    def repl(match: re.Match) -> str:
        name = match.group(1)
        val = os.environ.get(name)
        if val is None or val == "":
            raise RuntimeError(f"Newsletter sensor config references unset env var: {name}")
        return val
    return _ENV_VAR_RE.sub(repl, value)


class NewsletterEntryRID(RID):
    """Newsletter entry RID: orn:newsletter.<slug>.<digest>."""

    def __init__(self, slug: str, digest: str):
        super().__init__("orn", f"newsletter.{slug}.{digest}")


_HTML2TEXT = html2text.HTML2Text()
_HTML2TEXT.body_width = 0          # don't hard-wrap at 78 chars
_HTML2TEXT.ignore_links = False    # preserve [text](url) so URLs end up in KOI search
_HTML2TEXT.ignore_images = False   # keep ![alt](url) — image URLs often referenced
_HTML2TEXT.protect_links = True
_HTML2TEXT.skip_internal_links = True
_HTML2TEXT.unicode_snob = True


def _strip_html_to_text(html_body: str) -> str:
    """HTML → markdown-ish text via html2text. Preserves link URLs and
    image references; collapses excessive blank lines."""
    if not html_body:
        return ""
    try:
        text = _HTML2TEXT.handle(html_body)
    except Exception:
        # html2text occasionally chokes on malformed HTML. Fall back to a
        # tag-strip so we still index something.
        text = re.sub(r"<[^>]+>", " ", html_body)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_body(msg: email.message.Message) -> Tuple[str, str]:
    """Extract (text, html) from a parsed RFC5322 message."""
    text_body = ""
    html_body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if part.get_content_disposition() == "attachment":
                continue
            try:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                content = payload.decode(charset, errors="replace")
            except Exception:
                continue
            if ctype == "text/plain" and not text_body:
                text_body = content
            elif ctype == "text/html" and not html_body:
                html_body = content
    else:
        try:
            payload = msg.get_payload(decode=True) or b""
            charset = msg.get_content_charset() or "utf-8"
            content = payload.decode(charset, errors="replace")
        except Exception:
            content = ""
        if msg.get_content_type() == "text/html":
            html_body = content
        else:
            text_body = content
    return text_body, html_body


def _match_sender(routes: List[Dict[str, Any]], from_addr: str, list_id: str) -> Optional[Dict[str, Any]]:
    """First-match-wins routing. ``match`` is a substring matched against
    From and List-Id (case-insensitive)."""
    haystack = f"{from_addr.lower()} {list_id.lower()}"
    for route in routes:
        token = str(route.get("match", "")).lower()
        if token and token in haystack:
            return route
    return None


def _stable_digest(message_id: str, from_addr: str, subject: str, date: Optional[datetime]) -> str:
    parts = [message_id or "", from_addr or "", subject or "", date.isoformat() if date else ""]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


class NewslettersKOISensor:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.cfg, self.imap_cfg, self.routes, self.filtering = self._load(config_path)
        self.logger = self._setup_logging()

        self.koi_node = KOIPartialNode(
            node_name=self.cfg["name"],
            coordinator_url=self.cfg["coordinator_url"],
            poll_interval=30,
        )
        self.state = PersistentSensorState("newsletters", Path(__file__).parent)
        # Captured at start() so the IMAP poll thread can schedule emits
        # back onto the main asyncio loop where koi_node lives.
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None

    @staticmethod
    def _load(config_path: Path) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        with config_path.open() as f:
            data = yaml.safe_load(f) or {}
        sensor = data.get("sensor", {}) or {}
        imap = dict(data.get("imap", {}) or {})
        # Resolve password from env-var indirection.
        if "password_env" in imap:
            imap["password"] = _expand_env(f"${{{imap['password_env']}}}")
        elif "password" in imap and isinstance(imap["password"], str):
            imap["password"] = _expand_env(imap["password"])
        else:
            raise ValueError("imap.password_env or imap.password is required")
        imap.setdefault("host", "imap.gmail.com")
        imap.setdefault("port", 993)
        imap.setdefault("ssl", True)
        imap.setdefault("folders", ["INBOX"])

        routes = data.get("newsletters", []) or []
        for r in routes:
            for required in ("match", "slug", "access_source"):
                if required not in r:
                    raise ValueError(f"Newsletter route missing '{required}': {r}")
            r.setdefault("tags", [])
            r.setdefault("is_private", True)

        filtering = data.get("filtering", {}) or {}
        filtering.setdefault("max_age_days", 365)
        filtering.setdefault("min_body_length", 200)
        filtering.setdefault("max_email_size", 10 * 1024 * 1024)
        filtering.setdefault("default_route", None)

        cfg = {
            "name": sensor.get("name", "newsletters-sensor"),
            "node_id": sensor.get("node_id", "koi-sensor-newsletters-001"),
            "coordinator_url": sensor.get("coordinator_url", "http://localhost:8005"),
            "poll_interval": int(sensor.get("poll_interval", 600)),
        }
        return cfg, imap, routes, filtering

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("koi.sensor.newsletters")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            )
            logger.addHandler(handler)
        return logger

    def _imap_connect(self) -> imaplib.IMAP4:
        host = self.imap_cfg["host"]
        port = int(self.imap_cfg["port"])
        if self.imap_cfg.get("ssl", True):
            context = ssl.create_default_context()
            conn = imaplib.IMAP4_SSL(host, port, ssl_context=context)
        else:
            conn = imaplib.IMAP4(host, port)
            if self.imap_cfg.get("starttls"):
                conn.starttls(ssl.create_default_context())
        conn.login(self.imap_cfg["username"], self.imap_cfg["password"])
        return conn

    @staticmethod
    def _quote_folder(folder: str) -> str:
        return '"' + folder.replace('"', '\\"') + '"'

    def _select_folder(self, conn: imaplib.IMAP4, folder: str) -> Optional[int]:
        """SELECT a folder, return its UIDVALIDITY (or 0 if unavailable).
        Returns None only on outright SELECT failure."""
        status, sel_data = conn.select(self._quote_folder(folder), readonly=True)
        if status != "OK":
            self.logger.error(f"select {folder} failed: status={status} data={sel_data}")
            return None
        # Best-effort UIDVALIDITY lookup. Some servers/imaplib versions don't
        # populate untagged_responses by the time response() is called; in
        # that case we fall back to 0, which still scopes the watermark
        # correctly for normal operation. UIDVALIDITY changes (rare) would
        # cause a one-time re-emit on the next run if we missed them — fine
        # for newsletters.
        try:
            uidval_status, uidval = conn.response("UIDVALIDITY")
            if uidval_status == "OK" and uidval and uidval[0]:
                return int(uidval[0])
        except Exception as e:
            self.logger.warning(f"UIDVALIDITY fetch failed for {folder}: {e}")
        return 0

    def _state_key(self, folder: str, uidvalidity: int) -> str:
        return f"folder:{folder}:uidvalidity:{uidvalidity}:max_uid"

    def _get_max_uid(self, folder: str, uidvalidity: int) -> int:
        return int(self.state.metadata.get(self._state_key(folder, uidvalidity), 0))

    def _set_max_uid(self, folder: str, uidvalidity: int, uid: int) -> None:
        key = self._state_key(folder, uidvalidity)
        prev = int(self.state.metadata.get(key, 0))
        if uid > prev:
            self.state.metadata[key] = uid

    async def send_heartbeat_event(self, response_to: Optional[str] = None) -> None:
        try:
            heartbeat_data = {
                "type": "sensor_heartbeat",
                "sensor_id": self.cfg["name"],
                "sensor_type": "newsletters",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "active",
                "monitoring": [r["slug"] for r in self.routes],
                "items_tracked": len(self.state.processed),
            }
            if response_to:
                heartbeat_data["response_to"] = response_to
            heartbeat_document = {
                "id": f"newsletters_heartbeat_{int(datetime.now().timestamp())}",
                "title": "Newsletters Sensor Heartbeat",
                "url": "",
                "type": "heartbeat",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "content": json.dumps(heartbeat_data),
                "metadata": {
                    "sensor_type": "newsletters",
                    "sensor_id": self.cfg["name"],
                    "event_type": "HEARTBEAT",
                },
            }
            bundle = document_to_bundle(heartbeat_document)
            await self.koi_node.emit_new_event(bundle)
        except Exception as e:
            self.logger.error(f"Heartbeat error: {e}")

    async def send_periodic_heartbeats(self) -> None:
        while self.koi_node.running:
            await asyncio.sleep(1800)
            await self.send_heartbeat_event()

    async def start(self) -> None:
        self.logger.info(
            f"Starting newsletters sensor: {len(self.routes)} routes, "
            f"folders={self.imap_cfg['folders']}"
        )
        self._main_loop = asyncio.get_running_loop()
        self.logger.info("step: koi_node.start()")
        await self.koi_node.start()
        self.logger.info(f"step: koi_node started; running={getattr(self.koi_node, 'running', '?')}")
        self.logger.info("step: send_heartbeat_event()")
        await self.send_heartbeat_event()
        self.logger.info("step: heartbeat sent; entering poll loop")
        asyncio.create_task(self.send_periodic_heartbeats())

        while getattr(self.koi_node, "running", True):
            self.logger.info("step: poll_once()")
            try:
                await self.poll_once()
                self.state.save()
                self.logger.info("step: poll_once finished, sleeping")
            except Exception as e:
                self.logger.error(f"poll error: {e}", exc_info=True)
            await asyncio.sleep(self.cfg["poll_interval"])

    async def stop(self) -> None:
        self.logger.info("Stopping newsletters sensor")
        await self.koi_node.stop()

    async def poll_once(self) -> None:
        # IMAP is sync; run it in a thread so we don't block the event loop.
        await asyncio.to_thread(self._poll_sync)

    def _poll_sync(self) -> None:
        try:
            conn = self._imap_connect()
        except Exception as e:
            self.logger.error(f"IMAP connect failed: {e}")
            return
        try:
            for folder in self.imap_cfg["folders"]:
                uidvalidity = self._select_folder(conn, folder)
                if uidvalidity is None:
                    self.logger.error(f"[{folder}] SELECT failed; skipping")
                    continue
                self._poll_folder(conn, folder, uidvalidity)
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def _poll_folder(self, conn: imaplib.IMAP4, folder: str, uidvalidity: int) -> None:
        since_uid = self._get_max_uid(folder, uidvalidity)
        # Use server-side UID search "since_uid+1:*" — Gmail honors this.
        criteria = f"{since_uid + 1}:*" if since_uid > 0 else "1:*"
        status, data = conn.uid("SEARCH", None, "UID", criteria)
        if status != "OK" or not data or not data[0]:
            self.logger.info(f"[{folder}] poll: 0 new (since uid={since_uid})")
            return
        uids = [u for u in data[0].split() if int(u) > since_uid]
        if not uids:
            self.logger.info(f"[{folder}] poll: 0 new (since uid={since_uid})")
            return
        self.logger.info(f"[{folder}] poll: {len(uids)} new UIDs (since {since_uid}, uidvalidity={uidvalidity})")

        cutoff = datetime.now(timezone.utc) - timedelta(days=int(self.filtering["max_age_days"]))
        max_size = int(self.filtering["max_email_size"])

        for uid_b in uids:
            uid = int(uid_b)
            try:
                status, msg_data = conn.uid("FETCH", uid_b, "(BODY.PEEK[] RFC822.SIZE)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue
                first = msg_data[0]
                if not isinstance(first, tuple):
                    continue
                envelope, raw_bytes = first[0], first[1]
                size_match = re.search(rb"RFC822\.SIZE (\d+)", envelope or b"")
                size = int(size_match.group(1)) if size_match else len(raw_bytes)
                if size > max_size:
                    self.logger.debug(f"[{folder}] UID {uid} too large ({size}b) — skip")
                    self._set_max_uid(folder, uidvalidity, uid)
                    continue
                if self._process_message(folder, uid, raw_bytes, cutoff):
                    self._set_max_uid(folder, uidvalidity, uid)
                else:
                    # Even if we skipped (paywall, age, no match), advance the
                    # watermark so we don't re-fetch the same UID forever.
                    self._set_max_uid(folder, uidvalidity, uid)
            except Exception as e:
                self.logger.error(f"[{folder}] UID {uid} fetch error: {e}")

    def _process_message(self, folder: str, uid: int, raw: bytes, cutoff: datetime) -> bool:
        try:
            msg = email.message_from_bytes(raw, policy=policy.default)
        except Exception as e:
            self.logger.error(f"[{folder}] UID {uid} parse error: {e}")
            return False

        # Header pulls
        from_raw = str(msg.get("From", ""))
        _, from_addr = parseaddr(from_raw)
        from_addr = (from_addr or "").lower()
        list_id = str(msg.get("List-Id", "") or msg.get("List-Post", ""))
        subject = str(msg.get("Subject", "") or "(No Subject)").strip()
        message_id = str(msg.get("Message-ID", "") or "").strip()
        date_str = str(msg.get("Date", "") or "")
        try:
            date = parsedate_to_datetime(date_str) if date_str else None
            if date and date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
        except Exception:
            date = None

        if date and date < cutoff:
            self.logger.debug(f"[{folder}] UID {uid} too old ({date}) — skip")
            return False

        # Sender routing
        route = _match_sender(self.routes, from_addr, list_id)
        if route is None:
            default_match = self.filtering.get("default_route")
            if default_match:
                route = next((r for r in self.routes if r["slug"] == default_match), None)
        if route is None:
            self.logger.info(f"[{folder}] UID {uid} no route for from={from_addr} list-id={list_id} — skip")
            return False

        # Body extraction.
        # Newsletters: prefer the HTML body via html2text — it retains
        # link URLs, image refs, lists, and blockquotes. The plain-text
        # part Substack ships alongside is a stripped fallback that often
        # drops formatting cues we want indexed.
        text_part, html_part = _extract_body(msg)
        body_text = ""
        if html_part:
            body_text = _strip_html_to_text(html_part)
        if (not body_text or len(body_text) < int(self.filtering["min_body_length"])) and text_part:
            body_text = text_part
        if not body_text or len(body_text) < int(self.filtering["min_body_length"]):
            self.logger.debug(f"[{folder}] UID {uid} body too short — skip")
            return False
        text_body = body_text
        html_body = html_part

        digest = _stable_digest(message_id, from_addr, subject, date)
        rid_obj = NewsletterEntryRID(route["slug"], digest)
        rid_str = rid_obj.to_string()

        if self.state.is_processed(rid_str):
            return True  # already emitted; advance watermark below

        published_iso = date.isoformat() if date else None
        # Try to find a canonical post URL in the email body. Substack and
        # most newsletter platforms include one near the top of the HTML.
        url = ""
        url_match = re.search(r'https?://[^\s"<>]+', html_body or text_body)
        if url_match:
            url = url_match.group(0)

        full_text = f"{subject}\n\n{text_body}".strip()

        document = {
            "id": f"newsletter_{route['slug']}_{digest}",
            "source": f"newsletters:{route['slug']}",
            "source_type": "newsletter",
            "rid": rid_str,
            "url": url,
            "title": subject,
            "content": full_text,
            "metadata": {
                "title": subject,
                "author": from_raw,
                "from_address": from_addr,
                "list_id": list_id,
                "url": url,
                "newsletter_slug": route["slug"],
                "tags": list(route.get("tags") or []),
                # Privacy / access control (Notion-sensor pattern).
                "is_private": bool(route["is_private"]),
                "access_source": route["access_source"],
                # Dates
                "published_at": published_iso,
                "published_date": published_iso,
                "published_confidence": 0.95 if published_iso else 0.0,
                # Bookkeeping
                "imap_folder": folder,
                "imap_uid": uid,
                "message_id": message_id,
                "word_count": len(full_text.split()),
                "collection_method": "newsletters_sensor",
                "koi_sensor": self.cfg["name"],
            },
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "last_modified": published_iso,
            "tags": list(route.get("tags") or []),
        }

        self.state.mark_pending(route["slug"], rid_str)
        try:
            bundle = document_to_bundle(document, self.koi_node.node_id)
            success = self._emit_blocking(bundle)
        except Exception as e:
            self.state.clear_pending(route["slug"], rid_str)
            self.logger.error(f"[{folder}] UID {uid} emit failed: {e}")
            return False

        if success:
            self.state.mark_processed(route["slug"], rid_str)
            privacy = "🔒" if route["is_private"] else "🌐"
            self.logger.info(
                f"[{folder}] {privacy} {route['slug']} NEW: {subject[:80]}"
            )
            return True
        self.state.clear_pending(route["slug"], rid_str)
        return False

    async def ingest_mbox(self, mbox_path: Path) -> Dict[str, int]:
        """One-shot import of a Google Takeout mbox file.

        Reuses the same parsing / routing / bundle-emit path as the live
        IMAP poller via ``_process_message``. Idempotent — messages whose
        RID is already in the processed set are skipped (the existing
        is_processed gate inside _process_message handles this).

        Does not touch IMAP watermarks or open an IMAP connection.
        """
        if not mbox_path.exists():
            raise FileNotFoundError(f"mbox file not found: {mbox_path}")

        self._main_loop = asyncio.get_running_loop()
        self.logger.info(f"mbox ingest: starting from {mbox_path}")
        await self.koi_node.start()
        await self.send_heartbeat_event()

        cutoff = datetime.now(timezone.utc) - timedelta(
            days=int(self.filtering["max_age_days"])
        )
        max_size = int(self.filtering["max_email_size"])
        SAVE_EVERY = 25

        stats = {"emitted": 0, "already_processed": 0, "skipped": 0, "errors": 0}

        def _do_ingest() -> None:
            mb = mailbox.mbox(str(mbox_path))
            try:
                for idx, msg in enumerate(mb):
                    try:
                        raw = msg.as_bytes()
                    except Exception as e:
                        self.logger.error(f"[mbox] msg {idx} as_bytes error: {e}")
                        stats["errors"] += 1
                        continue
                    size = len(raw)
                    if size > max_size:
                        self.logger.debug(
                            f"[mbox] msg {idx} too large ({size}b) — skip"
                        )
                        stats["skipped"] += 1
                        continue
                    before = len(self.state.processed)
                    try:
                        ok = self._process_message("mbox", idx, raw, cutoff)
                    except Exception as e:
                        self.logger.error(
                            f"[mbox] msg {idx} process error: {e}", exc_info=True
                        )
                        stats["errors"] += 1
                        continue
                    if ok:
                        if len(self.state.processed) > before:
                            stats["emitted"] += 1
                        else:
                            stats["already_processed"] += 1
                    else:
                        stats["skipped"] += 1

                    total = sum(stats.values())
                    if total and total % SAVE_EVERY == 0:
                        self.state.save()
                        self.logger.info(
                            f"[mbox] progress: {total} seen "
                            f"(emitted={stats['emitted']}, "
                            f"already={stats['already_processed']}, "
                            f"skipped={stats['skipped']}, "
                            f"errors={stats['errors']})"
                        )
            finally:
                mb.close()

        await asyncio.to_thread(_do_ingest)
        self.state.save()
        await self.send_heartbeat_event()
        self.logger.info(
            f"mbox ingest: done — emitted={stats['emitted']}, "
            f"already_processed={stats['already_processed']}, "
            f"skipped={stats['skipped']}, errors={stats['errors']}"
        )
        return stats

    def _emit_blocking(self, bundle) -> bool:
        """Bridge sync IMAP polling into the asyncio loop running koi_node.

        Called from a worker thread (via asyncio.to_thread); cannot call
        emit_new_event directly because it's a coroutine on a different
        loop. Schedules the coroutine onto the captured main loop and
        waits for the result.
        """
        if self._main_loop is None:
            self.logger.error("main loop not captured; sensor not started?")
            return False
        future = asyncio.run_coroutine_threadsafe(
            self.koi_node.emit_new_event(bundle), self._main_loop
        )
        try:
            return bool(future.result(timeout=30))
        except Exception as e:
            self.logger.error(f"emit blocking call failed: {e}")
            return False


def _resolve_config_path() -> Path:
    explicit = os.environ.get("NEWSLETTERS_SENSOR_CONFIG")
    if explicit:
        return Path(explicit)
    return Path(__file__).parent / "config.yaml"


async def main():
    parser = argparse.ArgumentParser(description="KOI newsletters sensor")
    parser.add_argument(
        "--ingest-mbox",
        type=Path,
        metavar="PATH",
        help=(
            "One-shot mode: import a Google Takeout mbox file through the "
            "same parsing/routing/bundle-emit path as live IMAP polling, "
            "then exit. Idempotent — messages with RIDs already in the "
            "processed set are skipped. Does not connect to IMAP."
        ),
    )
    args = parser.parse_args()

    config_path = _resolve_config_path()
    sensor = NewslettersKOISensor(config_path)

    if args.ingest_mbox is not None:
        try:
            stats = await sensor.ingest_mbox(args.ingest_mbox)
        finally:
            await sensor.stop()
        if stats["errors"]:
            raise SystemExit(2)
        return

    try:
        await sensor.start()
    except KeyboardInterrupt:
        await sensor.stop()


if __name__ == "__main__":
    asyncio.run(main())
