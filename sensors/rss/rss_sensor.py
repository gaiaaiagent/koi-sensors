"""
KOI Sensor Network - Generic RSS/Atom Sensor

Polls a configurable list of RSS/Atom feeds and emits KOI bundles for each
new entry. Supports per-feed privacy via ``is_private`` + ``access_source``
metadata (consumed by koi-processor exactly like the Notion sensor).

URLs in config.yaml may contain ``${VAR}`` placeholders that are resolved
from the process environment at load time so paid-feed tokens (e.g.
Substack private RSS) live in the .env file, not the repo.
"""

import asyncio
import hashlib
import html
import json
import logging
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.request import Request, urlopen

import aiohttp
import feedparser
import yaml

from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.rid_system import RID
from koi_protocol.core.bundle_system import document_to_bundle
from shared.persistent_state import PersistentSensorState


# Cloudflare and similar gateways block default Python user-agents.
# Use a browser-like UA on every feedparser request and aiohttp fetch.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
feedparser.USER_AGENT = _BROWSER_UA

_INVALID_XML_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
_ENV_VAR_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


class RSSEntryRID(RID):
    """RSS entry resource identifier: orn:rss.<feed_slug>.<digest>."""

    def __init__(self, feed_slug: str, digest: str):
        super().__init__("orn", f"rss.{feed_slug}.{digest}")


def _strip_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _entry_value(entry: Any, *names: str) -> str:
    for name in names:
        value = getattr(entry, name, None)
        if value:
            return str(value)
    return ""


def _published_at(entry: Any) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    for attr in ("published", "updated", "created"):
        s = getattr(entry, attr, None)
        if s:
            try:
                dt = parsedate_to_datetime(s)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _stable_digest(feed_url: str, entry: Any, title: str, published: Optional[datetime]) -> Optional[str]:
    raw_id = _entry_value(entry, "link", "id", "guid")
    if not raw_id:
        published_key = published.isoformat() if published else _entry_value(entry, "published", "updated")
        if title and published_key:
            raw_id = f"{title}|{published_key}"
        elif title:
            raw_id = f"{title}|{_entry_value(entry, 'link') or _strip_html(_entry_value(entry, 'summary'))[:100]}"
    if not raw_id:
        return None
    return hashlib.sha256(f"{feed_url}|{raw_id}".encode("utf-8")).hexdigest()[:16]


def _expand_env(value: str) -> str:
    """Replace ``${VAR}`` placeholders with values from os.environ."""
    def repl(match: re.Match) -> str:
        name = match.group(1)
        val = os.environ.get(name)
        if val is None or val == "":
            raise RuntimeError(f"RSS feed config references unset env var: {name}")
        return val
    return _ENV_VAR_RE.sub(repl, value)


def _load_feeds(config_path: Path) -> List[Dict[str, Any]]:
    with config_path.open() as f:
        data = yaml.safe_load(f) or {}
    feeds = []
    for feed in data.get("feeds", []):
        if not feed.get("enabled", True):
            continue
        if not feed.get("url") or not feed.get("slug"):
            raise ValueError(f"RSS feed missing url/slug: {feed}")
        # Resolve env vars in URL (e.g. ${RSS_NATE_SUBSTACK_TOKEN})
        feed = dict(feed)
        feed["url"] = _expand_env(feed["url"])
        feed.setdefault("tags", [])
        feed.setdefault("domain", "other")
        feed.setdefault("check_interval", 3600)
        feed.setdefault("is_private", False)
        feed.setdefault("access_source", f"rss-{feed['slug']}")
        feeds.append(feed)
    return feeds


def _load_config(config_path: Path) -> Dict[str, Any]:
    with config_path.open() as f:
        data = yaml.safe_load(f) or {}
    sensor_cfg = data.get("sensor", {}) or {}
    http_cfg = data.get("http", {}) or {}
    return {
        "name": sensor_cfg.get("name", "rss-sensor"),
        "node_id": sensor_cfg.get("node_id", "koi-sensor-rss-001"),
        "coordinator_url": sensor_cfg.get("coordinator_url", "http://localhost:8005"),
        "user_agent": http_cfg.get("user_agent", _BROWSER_UA),
        "timeout_seconds": int(http_cfg.get("timeout_seconds", 30)),
        "request_delay": float(http_cfg.get("request_delay", 1.0)),
        "max_items_per_check": int(
            (data.get("collection", {}) or {}).get("max_items_per_check", 50)
        ),
        "min_content_length": int(
            (data.get("collection", {}) or {}).get("min_content_length", 100)
        ),
    }


class RSSKOISensor:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.cfg = _load_config(config_path)
        self.feeds = _load_feeds(config_path)
        self.logger = self._setup_logging()

        self.koi_node = KOIPartialNode(
            node_name=self.cfg["name"],
            coordinator_url=self.cfg["coordinator_url"],
            poll_interval=30,
        )

        self.state = PersistentSensorState("rss", Path(__file__).parent)
        self.session: Optional[aiohttp.ClientSession] = None

    def _setup_logging(self):
        logger = logging.getLogger("koi.sensor.rss")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            )
            logger.addHandler(handler)
        return logger

    async def send_heartbeat_event(self, response_to: Optional[str] = None):
        try:
            heartbeat_data = {
                "type": "sensor_heartbeat",
                "sensor_id": self.cfg["name"],
                "sensor_type": "rss",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "active",
                "monitoring": [feed["slug"] for feed in self.feeds],
                "items_tracked": len(self.state.processed),
            }
            if response_to:
                heartbeat_data["response_to"] = response_to

            heartbeat_document = {
                "id": f"rss_heartbeat_{int(datetime.now().timestamp())}",
                "title": "RSS Sensor Heartbeat",
                "url": "",
                "type": "heartbeat",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "content": json.dumps(heartbeat_data),
                "metadata": {
                    "sensor_type": "rss",
                    "sensor_id": self.cfg["name"],
                    "event_type": "HEARTBEAT",
                },
            }
            bundle = document_to_bundle(heartbeat_document)
            await self.koi_node.emit_new_event(bundle)
            if not response_to:
                self.logger.info("Sent heartbeat to coordinator")
        except Exception as e:
            self.logger.error(f"Heartbeat error: {e}")

    async def send_periodic_heartbeats(self):
        while self.koi_node.running:
            await asyncio.sleep(1800)
            await self.send_heartbeat_event()

    async def start(self):
        self.logger.info(f"Starting RSS sensor with {len(self.feeds)} feeds")

        await self.koi_node.start()
        await self.send_heartbeat_event()
        asyncio.create_task(self.send_periodic_heartbeats())

        connector = aiohttp.TCPConnector(limit=10, limit_per_host=2)
        timeout = aiohttp.ClientTimeout(total=self.cfg["timeout_seconds"])
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"User-Agent": self.cfg["user_agent"]},
        )

        tasks = [asyncio.create_task(self.monitor_feed(feed)) for feed in self.feeds]
        await asyncio.gather(*tasks)

    async def stop(self):
        self.logger.info("Stopping RSS sensor")
        if self.session:
            await self.session.close()
        await self.koi_node.stop()

    async def monitor_feed(self, feed: Dict[str, Any]):
        slug = feed["slug"]
        interval = int(feed.get("check_interval", 3600))
        privacy = "🔒 PRIVATE" if feed["is_private"] else "🌐 PUBLIC"
        self.logger.info(f"[{slug}] {privacy} access_source={feed['access_source']} interval={interval}s")

        while self.koi_node.running:
            try:
                await self.poll_feed(feed)
                self.state.save()
            except Exception as e:
                self.logger.error(f"[{slug}] poll error: {e}")
            await asyncio.sleep(interval)

    async def poll_feed(self, feed: Dict[str, Any]):
        slug = feed["slug"]
        url = feed["url"]

        rss_text = await self._fetch_feed_text(url)
        if rss_text is None:
            return

        parsed = feedparser.parse(rss_text)
        if not parsed.entries and getattr(parsed, "bozo", False):
            sanitized = _INVALID_XML_CHARS.sub("", rss_text)
            parsed = feedparser.parse(sanitized)
            if parsed.entries:
                self.logger.info(f"[{slug}] recovered feed after XML sanitization")

        new_count = 0
        for entry in parsed.entries[: self.cfg["max_items_per_check"]]:
            try:
                if await self._process_entry(feed, entry):
                    new_count += 1
                    await asyncio.sleep(self.cfg["request_delay"])
            except Exception as e:
                self.logger.error(f"[{slug}] entry error: {e}")

        if new_count:
            self.logger.info(f"[{slug}] emitted {new_count} new entries")

    async def _fetch_feed_text(self, url: str) -> Optional[str]:
        try:
            assert self.session is not None
            async with self.session.get(url) as response:
                if response.status != 200:
                    self.logger.warning(f"HTTP {response.status} for {url}")
                    return None
                return await response.text()
        except Exception as e:
            self.logger.error(f"Fetch failed for {url}: {e}")
            # Fallback: blocking urlopen with explicit UA. Some feeds reject
            # aiohttp's negotiated TLS cipher set but accept urlopen.
            try:
                req = Request(url, headers={"User-Agent": _BROWSER_UA})
                with urlopen(req, timeout=self.cfg["timeout_seconds"]) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except Exception as e2:
                self.logger.error(f"urlopen fallback also failed for {url}: {e2}")
                return None

    async def _process_entry(self, feed: Dict[str, Any], entry: Any) -> bool:
        slug = feed["slug"]
        title = _strip_html(_entry_value(entry, "title")) or "(untitled)"
        summary = _strip_html(_entry_value(entry, "summary", "description"))
        link = _entry_value(entry, "link")
        author = _entry_value(entry, "author")
        published = _published_at(entry)

        digest = _stable_digest(feed["url"], entry, title, published)
        if not digest:
            return False

        rid_obj = RSSEntryRID(slug, digest)
        rid_str = rid_obj.to_string()

        # Idempotency: persistent state tracks RIDs we've already emitted.
        if self.state.is_processed(rid_str):
            return False

        # Substack and many newsletter feeds put the body in 'content' (list of dicts).
        body_html = ""
        if hasattr(entry, "content") and entry.content:
            try:
                body_html = entry.content[0].get("value", "") if isinstance(entry.content[0], dict) else str(entry.content[0])
            except (AttributeError, IndexError):
                body_html = ""
        body_text = _strip_html(body_html) if body_html else summary

        full_text = f"{title}\n\n{body_text}".strip()
        if len(full_text) < self.cfg["min_content_length"]:
            self.logger.debug(f"[{slug}] skip short entry: {title}")
            return False

        # Carry per-entry tags from feed config + RSS categories.
        tags = list(feed.get("tags") or [])
        for tag in getattr(entry, "tags", []) or []:
            term = getattr(tag, "term", None)
            if term and term not in tags:
                tags.append(term)

        published_iso = published.isoformat() if published else None

        document = {
            "id": f"rss_{slug}_{digest}",
            "source": f"rss:{slug}",
            "source_type": "rss",
            "rid": rid_str,
            "url": link,
            "title": title,
            "content": full_text,
            "metadata": {
                # Provenance
                "title": title,
                "author": author or None,
                "url": link,
                "feed_url": feed["url"],
                "feed_slug": slug,
                "domain": feed.get("domain", "other"),
                "tags": tags,

                # Privacy / access control (Notion-sensor pattern; see migration 015)
                "is_private": bool(feed["is_private"]),
                "access_source": feed["access_source"],

                # Publication date
                "published_at": published_iso,
                "published_date": published_iso,
                "published_confidence": 0.9 if published_iso else 0.0,

                # Bookkeeping
                "summary": summary,
                "word_count": len(full_text.split()),
                "collection_method": "rss_sensor",
                "koi_sensor": self.cfg["name"],
            },
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "last_modified": published_iso,
            "tags": tags,
        }

        self.state.mark_pending(slug, rid_str)
        try:
            bundle = document_to_bundle(document, self.koi_node.node_id)
            success = await self.koi_node.emit_new_event(bundle)
        except Exception as e:
            self.state.clear_pending(slug, rid_str)
            self.logger.error(f"[{slug}] emit failed: {e}")
            return False

        if success:
            self.state.mark_processed(slug, rid_str)
            self.logger.info(f"[{slug}] NEW: {title}")
            return True

        self.state.clear_pending(slug, rid_str)
        return False


def _resolve_config_path() -> Path:
    explicit = os.environ.get("RSS_SENSOR_CONFIG")
    if explicit:
        return Path(explicit)
    return Path(__file__).parent / "config.yaml"


async def main():
    config_path = _resolve_config_path()
    sensor = RSSKOISensor(config_path)
    try:
        await sensor.start()
    except KeyboardInterrupt:
        await sensor.stop()


if __name__ == "__main__":
    asyncio.run(main())
