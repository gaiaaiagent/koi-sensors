#!/usr/bin/env python3
"""
KOI Notion Sensor - Real-time monitoring for Notion databases and pages
Integrates with Notion API to monitor workspace content changes
"""

print("[STARTUP] Starting imports...")
import asyncio
print("[STARTUP] asyncio imported")
import aiohttp
print("[STARTUP] aiohttp imported")
import json
import hashlib
import re
import tempfile
import subprocess
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta
from pathlib import Path
import os
from urllib.parse import urlparse, quote
print("[STARTUP] standard libs imported")

# KOI Protocol imports
import sys
# Add parent.parent to get to koi-sensors root where koi_protocol is
sys.path.append(str(Path(__file__).parent.parent.parent))
# Alternative path for when running from sensors/notion directory
if not any('koi_protocol' in p for p in sys.path):
    sys.path.insert(0, '../..')
print(f"[STARTUP] sys.path includes: {sys.path[:3]}")

print("[STARTUP] Importing KOI modules...")
from koi_protocol.nodes.koi_node import KOIPartialNode
print("[STARTUP] KOIPartialNode imported")
from koi_protocol.core.rid_system import RID, ORN
print("[STARTUP] RID, ORN imported")
from koi_protocol.core.bundle_system import Bundle, document_to_bundle
print("[STARTUP] Bundle imported")
from shared.persistent_state import PersistentSensorState
print("[STARTUP] PersistentSensorState imported")


class NotionPageRID(ORN):
    """Notion page RID: orn:notion.page:workspace/page_id"""
    namespace = "notion.page"
    
    def __init__(self, workspace: str, page_id: str):
        self.workspace = workspace
        self.page_id = page_id.replace('-', '')  # Remove hyphens from Notion IDs
        super().__init__()
    
    @classmethod
    def from_reference(cls, reference: str):
        workspace, page_id = reference.split('/', 1)
        return cls(workspace, page_id)
    
    @property
    def reference(self) -> str:
        return f"{self.workspace}/{self.page_id}"


class NotionDatabaseRID(ORN):
    """Notion database RID: orn:notion.database:workspace/database_id"""
    namespace = "notion.database"

    def __init__(self, workspace: str, database_id: str):
        self.workspace = workspace
        self.database_id = database_id.replace('-', '')
        super().__init__()

    @classmethod
    def from_reference(cls, reference: str):
        workspace, database_id = reference.split('/', 1)
        return cls(workspace, database_id)

    @property
    def reference(self) -> str:
        return f"{self.workspace}/{self.database_id}"


class PIIFilter:
    """Filter to detect and redact personally identifiable information from content"""

    # PII patterns to detect
    PATTERNS = {
        'email': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'telegram': r'(?:(?:https?://)?(?:t\.me|telegram\.me)/|@)([A-Za-z0-9_]{5,32})',
        'phone': r'(?:\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
        'discord': r'\b[A-Za-z0-9_]+#\d{4}\b',
    }

    def __init__(self, enabled: bool = True, redact_types: List[str] = None):
        """
        Initialize PII filter.

        Args:
            enabled: Whether filtering is enabled
            redact_types: List of PII types to redact (email, telegram, phone, discord)
                         If None, all types are redacted
        """
        self.enabled = enabled
        self.redact_types = redact_types or list(self.PATTERNS.keys())
        self._compiled_patterns = {
            pii_type: re.compile(pattern, re.IGNORECASE)
            for pii_type, pattern in self.PATTERNS.items()
            if pii_type in self.redact_types
        }

    def filter_content(self, content: str) -> str:
        """
        Filter PII from content, replacing with redaction markers.

        Args:
            content: Text content to filter

        Returns:
            Filtered content with PII redacted
        """
        if not self.enabled or not content:
            return content

        filtered = content
        for pii_type, pattern in self._compiled_patterns.items():
            # Replace with type-specific placeholder
            filtered = pattern.sub(f'[REDACTED_{pii_type.upper()}]', filtered)

        return filtered

    def should_skip_property(self, prop_type: str) -> bool:
        """
        Check if a property type should be skipped entirely.

        Args:
            prop_type: Notion property type (email, phone_number, etc.)

        Returns:
            True if property should be skipped
        """
        if not self.enabled:
            return False

        # Map Notion property types to our PII types
        pii_mapping = {
            'email': 'email',
            'phone_number': 'phone',
        }

        return pii_mapping.get(prop_type) in self.redact_types


class VideoTranscriber:
    """Transcribe video files using local Whisper model"""

    def __init__(self, model_size: str = "base", enabled: bool = True):
        """
        Initialize video transcriber.

        Args:
            model_size: Whisper model size (tiny, base, small, medium, large)
            enabled: Whether transcription is enabled
        """
        self.enabled = enabled
        self.model_size = model_size
        self._model = None
        self._whisper_available = None

    def _check_whisper_available(self) -> bool:
        """Check if Whisper is available"""
        if self._whisper_available is not None:
            return self._whisper_available

        try:
            import whisper
            self._whisper_available = True
            print("✓ Whisper transcription available")
        except ImportError:
            self._whisper_available = False
            print("⚠️ Whisper not installed - video transcription disabled")
            print("   Install with: pip install openai-whisper")

        return self._whisper_available

    def _load_model(self):
        """Load Whisper model (lazy loading)"""
        if self._model is not None:
            return self._model

        if not self._check_whisper_available():
            return None

        try:
            import whisper
            print(f"📥 Loading Whisper {self.model_size} model...")
            self._model = whisper.load_model(self.model_size)
            print(f"✓ Whisper model loaded")
            return self._model
        except Exception as e:
            print(f"❌ Failed to load Whisper model: {e}")
            return None

    async def download_video(self, url: str, session: aiohttp.ClientSession) -> Tuple[Optional[str], int]:
        """
        Download video to temporary file.

        Args:
            url: Video URL to download
            session: aiohttp session to use (Note: Notion S3 URLs don't need auth headers)

        Returns:
            Tuple of (path to downloaded file or None, HTTP status code)
        """
        try:
            # Create temp file
            suffix = ".mp4"  # Most Notion videos are mp4
            if ".webm" in url:
                suffix = ".webm"
            elif ".mov" in url:
                suffix = ".mov"

            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp_path = tmp.name

            # Download video - use a fresh session without Notion headers
            # Notion S3 signed URLs don't need/want the Notion auth headers
            print(f"   📥 Downloading video...")
            async with aiohttp.ClientSession() as download_session:
                async with download_session.get(url) as response:
                    if response.status != 200:
                        print(f"   ❌ Failed to download video: HTTP {response.status}")
                        return None, response.status

                    # Check size - skip very large videos
                    content_length = response.headers.get('Content-Length')
                    if content_length:
                        size_mb = int(content_length) / (1024 * 1024)
                        if size_mb > 500:  # Skip videos > 500MB
                            print(f"   ⚠️ Video too large ({size_mb:.1f}MB), skipping transcription")
                            return None, 200  # Not an error, just skipped
                        print(f"   Size: {size_mb:.1f}MB")

                    # Stream to file
                    with open(tmp_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)

            return tmp_path, 200

        except Exception as e:
            print(f"   ❌ Error downloading video: {e}")
            return None, 0

    def extract_audio(self, video_path: str) -> Optional[str]:
        """
        Extract audio from video using ffmpeg.

        Args:
            video_path: Path to video file

        Returns:
            Path to extracted audio file, or None on failure
        """
        try:
            audio_path = video_path.rsplit('.', 1)[0] + '.wav'

            # Use ffmpeg to extract audio
            cmd = [
                'ffmpeg', '-i', video_path,
                '-vn',  # No video
                '-acodec', 'pcm_s16le',  # PCM format
                '-ar', '16000',  # 16kHz sample rate (Whisper optimal)
                '-ac', '1',  # Mono
                '-y',  # Overwrite
                audio_path
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            if result.returncode != 0:
                print(f"   ❌ ffmpeg error: {result.stderr[:200]}")
                return None

            return audio_path

        except subprocess.TimeoutExpired:
            print(f"   ❌ Audio extraction timed out")
            return None
        except Exception as e:
            print(f"   ❌ Error extracting audio: {e}")
            return None

    def transcribe_audio(self, audio_path: str) -> Optional[str]:
        """
        Transcribe audio file using Whisper.

        Args:
            audio_path: Path to audio file

        Returns:
            Transcription text, or None on failure
        """
        model = self._load_model()
        if model is None:
            return None

        try:
            print(f"   🎙️ Transcribing audio...")
            result = model.transcribe(audio_path, language="en")
            text = result.get("text", "").strip()

            if text:
                print(f"   ✓ Transcribed {len(text)} characters")
            else:
                print(f"   ⚠️ No speech detected in audio")

            return text if text else None

        except Exception as e:
            print(f"   ❌ Transcription error: {e}")
            return None

    async def transcribe_video_url(
        self,
        url: str,
        session: aiohttp.ClientSession,
        refresh_url_callback: Optional[Any] = None
    ) -> Optional[str]:
        """
        Download and transcribe a video from URL.

        Args:
            url: Video URL
            session: aiohttp session
            refresh_url_callback: Optional async callback to get a fresh URL if the current one expired.
                                  Should return a new URL string or None.

        Returns:
            Transcription text, or None on failure
        """
        if not self.enabled:
            return None

        if not self._check_whisper_available():
            return None

        video_path = None
        audio_path = None
        current_url = url

        try:
            # Download video (with retry on expired URL)
            video_path, status = await self.download_video(current_url, session)

            # If URL expired (400/403), try refreshing
            if video_path is None and status in (400, 403) and refresh_url_callback:
                print(f"   🔄 URL expired, refreshing...")
                fresh_url = await refresh_url_callback()
                if fresh_url:
                    current_url = fresh_url
                    video_path, status = await self.download_video(current_url, session)

            if not video_path:
                return None

            # Extract audio
            audio_path = self.extract_audio(video_path)
            if not audio_path:
                return None

            # Transcribe
            transcript = self.transcribe_audio(audio_path)
            return transcript

        finally:
            # Cleanup temp files
            if video_path and os.path.exists(video_path):
                try:
                    os.unlink(video_path)
                except:
                    pass
            if audio_path and os.path.exists(audio_path):
                try:
                    os.unlink(audio_path)
                except:
                    pass


class NotionFetchError(RuntimeError):
    """A failed/incomplete API read, never equivalent to an empty result."""

    def __init__(self, resource: str, status=None, code="incomplete_read"):
        self.resource, self.status, self.code = resource, status, code
        super().__init__(f"Notion read failed: {resource} ({status or code})")

    def coverage(self):
        return {"resource": self.resource, "status": self.status, "code": self.code}


class NotionKOISensor:
    """KOI-compliant Notion monitoring sensor"""
    
    NOTION_API_VERSION = "2022-06-28"
    NOTION_API_BASE = "https://api.notion.com/v1"
    
    def __init__(self,
                 node_id: str = "koi-notion-sensor",
                 coordinator_url: str = "http://localhost:8005",
                 notion_token: str = None,
                 workspace_id: str = "regen",
                 pii_filter_enabled: bool = True,
                 pii_filter_types: List[str] = None,
                 transcribe_videos: bool = False,
                 whisper_model: str = "base",
                 skip_sections: List[str] = None,
                 skip_pages: List[str] = None,
                 is_private: bool = False,
                 access_source: str = None,
                 max_pages_per_poll: int = 25,
                 max_comment_targets: int = 100):
        """
        Initialize Notion sensor.

        Args:
            node_id: Unique identifier for this sensor
            coordinator_url: KOI coordinator URL
            notion_token: Notion API token
            workspace_id: Workspace identifier for RIDs
            pii_filter_enabled: Enable PII filtering
            pii_filter_types: List of PII types to filter
            transcribe_videos: Enable video transcription with Whisper
            whisper_model: Whisper model size (tiny, base, small, medium, large)
            skip_sections: List of heading names whose content should be skipped
                          (e.g., ["Projects"] to skip child_database under Projects heading)
            skip_pages: List of page IDs to skip entirely (e.g., archive pages with many videos)
            is_private: If True, data from this workspace requires OAuth authentication
            access_source: Identifier for which configuration determined privacy level
            max_pages_per_poll: Round-robin page snapshot budget per polling cycle
            max_comment_targets: Page plus block comment targets per page visit
        """
        self.node_id = node_id
        self.coordinator_url = coordinator_url

        # Use provided token or get from environment
        self.notion_token = notion_token or os.getenv('NOTION_INTEGRATION_SECRET')
        if not self.notion_token:
            raise ValueError("Notion integration secret required. Set NOTION_INTEGRATION_SECRET env var.")

        # Initialize KOI node
        self.koi_node = KOIPartialNode(
            node_name="notion-sensor",
            coordinator_url=self.coordinator_url,
            poll_interval=30
        )

        # Monitoring state
        self.monitored_databases: Dict[str, Dict[str, Any]] = {}
        self.monitored_pages: Dict[str, Dict[str, Any]] = {}

        # Persistent state for deterministic page tracking (replaces content_hashes)
        self.state = PersistentSensorState('notion', Path(__file__).parent)

        self.session: Optional[aiohttp.ClientSession] = None

        # Workspace identifier (extracted from pages/databases)
        self.workspace_id = workspace_id
        self.max_pages_per_poll = max(1, max_pages_per_poll)
        self.max_comment_targets = max(2, max_comment_targets)
        self.max_block_requests = 100
        self.max_api_pages = 100
        self.request_interval = 0.35  # Notion's average three requests/second
        self._last_api_request = 0

        # Privacy settings for access control
        self.is_private = is_private
        self.access_source = access_source or f"notion-{workspace_id}"

        # PII Filter for protecting personal data
        self.pii_filter = PIIFilter(
            enabled=pii_filter_enabled,
            redact_types=pii_filter_types
        )

        # Video transcription
        self.video_transcriber = VideoTranscriber(
            model_size=whisper_model,
            enabled=transcribe_videos
        )

        # Sections to skip (e.g., "Projects" to skip embedded project databases)
        self.skip_sections = [s.lower() for s in (skip_sections or [])]

        # Pages to skip entirely (e.g., archive pages with many videos)
        self.skip_pages = set(skip_pages or [])

        print(f"📝 KOI Notion Sensor initialized")
        print(f"   Node ID: {self.node_id}")
        print(f"   Coordinator: {self.coordinator_url}")
        print(f"   Workspace: {self.workspace_id}")
        print(f"   API Version: {self.NOTION_API_VERSION}")
        print(f"   Privacy: {'🔒 PRIVATE (requires OAuth)' if self.is_private else '🌐 PUBLIC'}")
        print(f"   Access Source: {self.access_source}")
        print(f"   PII Filter: {'enabled' if pii_filter_enabled else 'disabled'}")
        print(f"   Video Transcription: {'enabled' if transcribe_videos else 'disabled'}")
        if self.skip_sections:
            print(f"   Skip Sections: {', '.join(self.skip_sections)}")
        if self.skip_pages:
            print(f"   Skip Pages: {len(self.skip_pages)} page(s)")
    
    async def __aenter__(self):
        """Async context manager entry"""
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Notion-Version": self.NOTION_API_VERSION,
            "Content-Type": "application/json"
        }
        self.session = aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=30))

        # Start the KOI node to initialize its session
        await self.koi_node.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()

        # Stop the KOI node
        await self.koi_node.stop()
    
    async def search_workspace(self, query: str = None, filter_type: str = None) -> List[Dict]:
        """
        Search the Notion workspace for pages and databases

        Args:
            query: Optional search query
            filter_type: 'page' or 'database' to filter results
        """
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")

        search_params = {"page_size": 100}  # Max allowed by Notion API
        if query:
            search_params["query"] = query
        if filter_type:
            search_params["filter"] = {"property": "object", "value": filter_type}

        all_results = []
        has_more = True
        next_cursor = None

        try:
            while has_more:
                if next_cursor:
                    search_params["start_cursor"] = next_cursor

                async with self.session.post(
                    f"{self.NOTION_API_BASE}/search",
                    json=search_params
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        results = data.get("results", [])
                        all_results.extend(results)
                        has_more = data.get("has_more", False)
                        next_cursor = data.get("next_cursor")

                        # Continue fetching all results
                        # Remove the 150 limit to get ALL pages
                    else:
                        error = await response.text()
                        print(f"❌ Search failed: {response.status} - {error}")
                        break

            return all_results
        except Exception as e:
            print(f"❌ Error searching workspace: {e}")
            return []
    
    async def get_database(self, database_id: str) -> Optional[Dict]:
        """Get database metadata"""
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")
        
        try:
            async with self.session.get(
                f"{self.NOTION_API_BASE}/databases/{database_id}"
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error = await response.text()
                    print(f"❌ Failed to get database {database_id}: {error}")
                    return None
        except Exception as e:
            print(f"❌ Error getting database: {e}")
            return None
    
    async def query_database(self, database_id: str, 
                           filter_obj: Dict = None,
                           sorts: List[Dict] = None,
                           page_size: int = 100) -> List[Dict]:
        """
        Query a Notion database for pages
        
        Args:
            database_id: The database ID to query
            filter_obj: Optional filter object
            sorts: Optional sort configuration
            page_size: Number of results per page (max 100)
        """
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")
        
        query_params = {"page_size": min(page_size, 100)}
        if filter_obj:
            query_params["filter"] = filter_obj
        if sorts:
            query_params["sorts"] = sorts
        
        return await self._get_list(f"databases/{database_id}/query", query_params, method="post")

    async def get_page(self, page_id: str, strict: bool = False) -> Optional[Dict]:
        """Get page metadata; reconciliation needs explicit failure, not an empty page."""
        path = f"pages/{page_id}"
        try:
            await self._pace_request()
            async with self.session.get(f"{self.NOTION_API_BASE}/{path}") as response:
                if response.status != 200:
                    raise NotionFetchError(path, response.status, "http_error")
                page = await response.json()
                if (not isinstance(page, dict)
                        or page.get("id", "").replace('-', '') != page_id.replace('-', '')):
                    raise NotionFetchError(path, code="malformed_page")
                return page
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            if strict:
                raise NotionFetchError(path, code="transport_or_json_error") from exc
        except NotionFetchError:
            if strict:
                raise
        return None

    async def get_user(self, user_id: str) -> Optional[Dict]:
        """Get user details to retrieve name (not included in page responses)"""
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")

        try:
            async with self.session.get(
                f"{self.NOTION_API_BASE}/users/{user_id}"
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    return None
        except Exception as e:
            return None

    async def get_block(self, block_id: str) -> Optional[Dict]:
        """Fetch a single block to get fresh signed URLs (for video downloads)"""
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")

        try:
            async with self.session.get(
                f"{self.NOTION_API_BASE}/blocks/{block_id}"
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error = await response.text()
                    print(f"❌ Failed to get block {block_id}: {error}")
                    return None
        except Exception as e:
            print(f"❌ Error getting block: {e}")
            return None

    async def get_page_content(self, page_id: str, blocks: Optional[List[Dict]] = None) -> str:
        """
        Get the full content of a page as text, with PII filtering applied.
        Also handles:
        - Skipping content under configured section headings (e.g., "Projects")
        - Transcribing videos when enabled (unless page already has a transcript)

        Args:
            page_id: The page ID to retrieve content from
        """
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")

        # Get blocks from the page
        if blocks is None:
            blocks = await self.get_blocks(page_id)

        # First pass: check if page already has a transcript section
        # This avoids expensive video transcription when a human transcript exists
        has_existing_transcript = False
        for block in blocks:
            block_type = block.get("type", "")
            if block_type in ["heading_1", "heading_2", "heading_3"]:
                block_data = block.get(block_type, {})
                heading_text = self.extract_text_from_rich_text(block_data.get("rich_text", []))
                if heading_text and "transcript" in heading_text.lower():
                    has_existing_transcript = True
                    break

        if has_existing_transcript:
            print(f"   📝 Page has existing transcript, skipping video transcription")

        # Convert blocks to text with section awareness
        content_parts = []
        current_section = None  # Track which section we're in
        skip_until_next_heading = False

        for block in blocks:
            block_type = block.get("type", "")

            # Check if this is a heading block
            if block_type in ["heading_1", "heading_2", "heading_3"]:
                block_data = block.get(block_type, {})
                heading_text = self.extract_text_from_rich_text(block_data.get("rich_text", []))
                current_section = heading_text.lower() if heading_text else None

                # Check if this section should be skipped
                skip_until_next_heading = current_section in self.skip_sections
                if skip_until_next_heading:
                    print(f"   ⏭️ Skipping section: {heading_text}")
                    continue

            # Skip content if in a skipped section
            if skip_until_next_heading:
                continue

            # Handle video blocks with transcription (skip if page has existing transcript)
            if block_type == "video" and self.video_transcriber.enabled and not has_existing_transcript:
                text = await self._extract_video_with_transcription(block)
            else:
                text = self.extract_text_from_block(block)

            if text:
                content_parts.append(text)

        content = "\n\n".join(content_parts)

        # Apply PII filtering
        return self.pii_filter.filter_content(content)

    async def _extract_video_with_transcription(self, block: Dict) -> Optional[str]:
        """Avoid retranscribing unchanged recordings during comment reconciliation."""
        cache = self._poll_state("notion_video_cache_v1")
        block_id, edited = block.get("id"), block.get("last_edited_time")
        video = block.get("video", {})
        version = hashlib.sha256(json.dumps({"edited": edited, "type": video.get("type"),
            "caption": video.get("caption"), "external": video.get("external")}, sort_keys=True).encode()).hexdigest()
        cached = cache.get(block_id, {})
        if edited and cached.get("version") == version:
            # Respect a subsequently tightened PII policy on locally cached text.
            cached["content"] = self.pii_filter.filter_content(cached["content"])
            return cached["content"]
        content = self.pii_filter.filter_content(await self._render_video_with_transcription(block) or "")
        if block_id and edited and "**Transcript:**" in content:
            cache[block_id] = {"version": version, "content": content}
            while len(cache) > 256:
                cache.pop(next(iter(cache)))
        return content

    async def _render_video_with_transcription(self, block: Dict) -> Optional[str]:
        """
        Extract video block with optional transcription.

        Args:
            block: Video block from Notion API

        Returns:
            Text representation including transcription if available
        """
        block_id = block.get("id", "")
        block_data = block.get("video", {})
        video_type = block_data.get("type", "")
        caption = self.extract_text_from_rich_text(block_data.get("caption", []))

        # Get video URL
        video_url = None
        if video_type == "file":
            video_url = block_data.get("file", {}).get("url", "")
        elif video_type == "external":
            video_url = block_data.get("external", {}).get("url", "")

        # Build base text
        if video_type == "external":
            base_text = f"[Video: {video_url}]"
        elif video_type == "file":
            base_text = "[Video Recording]"
        else:
            base_text = "[Video]"

        if caption:
            base_text += f" - {caption}"

        # Try to transcribe if we have a file URL
        if video_url and video_type == "file" and self.video_transcriber.enabled:
            print(f"   🎬 Found video recording, attempting transcription...")

            # Create callback to refresh URL if it expired
            async def refresh_url():
                """Fetch fresh block data to get a new signed URL"""
                fresh_block = await self.get_block(block_id)
                if fresh_block:
                    fresh_data = fresh_block.get("video", {})
                    if fresh_data.get("type") == "file":
                        return fresh_data.get("file", {}).get("url", "")
                return None

            transcript = await self.video_transcriber.transcribe_video_url(
                video_url, self.session, refresh_url_callback=refresh_url
            )
            if transcript:
                return f"{base_text}\n\n**Transcript:**\n{transcript}"

        return base_text
    
    async def _pace_request(self):
        now = asyncio.get_running_loop().time()
        await asyncio.sleep(max(0, self.request_interval - (now - self._last_api_request)))
        self._last_api_request = asyncio.get_running_loop().time()

    async def _get_list(self, path: str, params: Optional[Dict] = None, method: str = "get") -> List[Dict]:
        """Read all API result pages or raise; partial lists are not snapshots."""
        values, cursors = [], set()
        query = {"page_size": 100, **(params or {})}
        for _ in range(self.max_api_pages):
            await self._pace_request()
            try:
                request = getattr(self.session, method)
                args = {"json" if method == "post" else "params": query}
                async with request(f"{self.NOTION_API_BASE}/{path}", **args) as response:
                    if response.status != 200:
                        # Do not log raw response bodies (may contain private content).
                        raise NotionFetchError(path, response.status, "http_error")
                    data = await response.json()
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
                raise NotionFetchError(path, code="transport_or_json_error") from exc
            if (not isinstance(data, dict) or not isinstance(data.get("results"), list)
                    or any(not isinstance(item, dict) for item in data["results"])):
                raise NotionFetchError(path, code="malformed_list")
            if data.get("request_status", {}).get("type") == "incomplete":
                raise NotionFetchError(path, code="incomplete_list")
            values.extend(data["results"])
            if data.get("has_more") is False:
                return values
            cursor = data.get("next_cursor")
            if data.get("has_more") is not True or not cursor or cursor in cursors:
                raise NotionFetchError(path, code="invalid_cursor")
            cursors.add(cursor)
            query["start_cursor"] = cursor
        raise NotionFetchError(path, code="pagination_budget_exhausted")

    async def get_blocks(self, block_id: str, page_size: int = 100) -> List[Dict]:
        """Paginated depth-first discovery with a bounded request/depth budget."""
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")
        blocks, visited = [], set()

        async def visit(parent, depth=0):
            if parent in visited or depth > 50 or len(visited) >= self.max_block_requests:
                raise NotionFetchError(f"blocks/{parent}/children", code="block_scan_budget_or_cycle")
            visited.add(parent)
            children = await self._get_list(f"blocks/{parent}/children", {"page_size": min(page_size, 100)})
            skipping = False
            for block in children:
                child_id = block.get("id")
                if not child_id:
                    raise NotionFetchError(f"blocks/{parent}/children", code="missing_block_id")
                if child_id in self.skip_pages or child_id.replace('-', '') in self.skip_pages:
                    continue
                kind = block.get("type", "")
                if kind in {"heading_1", "heading_2", "heading_3"}:
                    heading = self.extract_text_from_rich_text(block.get(kind, {}).get("rich_text", []))
                    skipping = heading.lower() in self.skip_sections
                if skipping:
                    # A heading inside an excluded subtree must not reopen it.
                    # Section boundaries are siblings in their original block tree.
                    continue
                blocks.append(block)
                if block.get("has_children") and kind not in {"child_page", "child_database"}:
                    await visit(child_id, depth + 1)
        await visit(block_id)
        return blocks

    def _visible_blocks(self, blocks: List[Dict]) -> List[Dict]:
        """Apply the same configured section exclusions to discussion discovery."""
        visible, skipping = [], False
        for block in blocks:
            kind = block.get("type", "")
            if kind in {"heading_1", "heading_2", "heading_3"}:
                title = self.extract_text_from_rich_text(block.get(kind, {}).get("rich_text", []))
                skipping = title.lower() in self.skip_sections
            if not skipping:
                visible.append(block)
        return visible

    async def _complete_properties(self, page: Dict) -> Dict:
        """Expand truncated people/relation values before replacing a snapshot."""
        properties = dict(page.get("properties", {}))
        for name, prop in properties.items():
            kind = prop.get("type")
            if kind not in {"people", "relation"}:
                continue
            values = prop.get(kind, [])
            if prop.get("has_more") or len(values) >= 25:
                prop_id = prop.get("id")
                if not prop_id:
                    raise NotionFetchError("page_properties", code="missing_property_id")
                # Property IDs returned by Notion are already URL-encoded.
                path = f"pages/{page['id']}/properties/{quote(prop_id, safe='%')}"
                items = await self._get_list(path)
                if any(item.get("type") != kind or not isinstance(item.get(kind), dict) for item in items):
                    raise NotionFetchError(path, code="malformed_property_item")
                properties[name] = {**prop, kind: [item[kind] for item in items], "has_more": False}
        return properties

    def _safe_person(self, person: Dict) -> Dict:
        """Retain useful attribution, never raw person/email/avatar objects."""
        result = {"id": person["id"]} if person.get("id") else {}
        if person.get("name"):
            result["name"] = self.pii_filter.filter_content(person["name"])
        return result

    async def _author(self, person: Dict) -> Dict:
        if person.get("id") and not person.get("name"):
            person = {**person, **(await self.get_user(person["id"]) or {})}
        return self._safe_person(person)

    def _poll_state(self, key: str) -> Dict:
        return self.state.metadata.setdefault(key, {}).setdefault(self.workspace_id, {})

    def _queue_document(self, document: Dict):
        """Queue only filtered, stable source data; checkpoint only after delivery."""
        key = document["state_key"]
        digest = hashlib.sha256(json.dumps({"title": document["title"],
            "content": document["content"], "metadata": document["metadata"]},
            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        hashes = self._poll_state("notion_document_hashes_v1")
        if hashes.get(key) == digest:
            # A failed B update can be superseded by a return to acknowledged A.
            self._poll_state("notion_outbox_v1").pop(key, None)
            return
        # Legacy page hashes keep an existing page an UPDATE during migration.
        old = hashes.get(key) or (self.state.metadata.get(f"hash_{key}") if not document["metadata"].get("comment_id") else None)
        document.update(event_type="UPDATE" if old else "NEW", content_hash=digest,
                        state_source=self.workspace_id)
        self._poll_state("notion_outbox_v1")[key] = document

    async def _comment_snapshot(self, page: Dict, blocks: List[Dict], base_metadata: Dict):
        """Observe unresolved comments; never infer deletion/resolution from absence."""
        page_id = page["id"]
        visible = self._visible_blocks(blocks)
        # A child-page block references another page. Querying its ID here would
        # attribute that page's discussion to this ancestor and oscillate its RID
        # metadata when the child is independently monitored.
        references = {"child_page", "child_database"}
        block_ids = list(dict.fromkeys(b["id"] for b in visible if b.get("type") not in references))
        offsets = self._poll_state("notion_comment_offsets_v1")
        limit = getattr(self, "max_comment_targets", 100) - 1
        offset = offsets.get(page_id, 0) % max(1, len(block_ids))
        selected = (block_ids[offset:] + block_ids[:offset])[:limit]
        offsets[page_id] = (offset + len(selected)) % max(1, len(block_ids))
        targets = [page_id] + selected
        comments, errors, successful = {}, [], 0
        for target in targets:
            try:
                items = await self._get_list("comments", {"block_id": target})
                if any(not item.get("id") or not item.get("discussion_id") for item in items):
                    raise NotionFetchError("comments", code="malformed_comment")
                for item in items:
                    previous = comments.get(item["id"])
                    if not previous or item.get("last_edited_time", "") >= previous.get("last_edited_time", ""):
                        comments[item["id"]] = item
                successful += 1
            except NotionFetchError as exc:
                errors.append({**exc.coverage(), "block_id": target})
                if target == page_id and exc.status in {401, 403}:
                    # Missing Read comments commonly affects the whole integration.
                    break
        for item in sorted(comments.values(), key=lambda c: c["id"]):
            author = await self._author(item.get("created_by", {}))
            parent = item.get("parent", {})
            parent_kind = parent.get("type")
            parent_id = parent.get(parent_kind) if parent_kind in {"page_id", "block_id"} else None
            url = base_metadata["page_url"]
            if parent_kind == "block_id" and parent_id:
                url += "#" + parent_id.replace('-', '')
            text = self.pii_filter.filter_content(self.extract_text_from_rich_text(item.get("rich_text", [])))
            metadata = {k: base_metadata[k] for k in ("page_id", "page_url", "workspace_id", "is_private", "access_source")}
            metadata.update(record_kind="comment", comment_id=item["id"], discussion_id=item["discussion_id"],
                            parent={"type": parent_kind, parent_kind: parent_id} if parent_id else {},
                            author_id=author.get("id"), author=author.get("name"),
                            created_time=item.get("created_time"), published_at=item.get("created_time"),
                            last_edited_time=item.get("last_edited_time"), last_modified=item.get("last_edited_time"),
                            url=url, source_url=url, observation_scope="unresolved_comments_only")
            self._queue_document({"source": "notion", "source_type": "notion", "id": item["id"],
                                  "title": "Comment on " + base_metadata["page_title"],
                                  "content": "Notion discussion comment (separate from page content):\n" + text,
                                  "url": url, "metadata": metadata,
                                  "rid": f"orn:notion.comment:{self.workspace_id}/{item['id']}",
                                  "state_key": "comment:" + item["id"]})
        return {"scope": "unresolved_comments_only", "resolved_history_available": False,
                "status": "complete" if not errors and len(selected) == len(block_ids) else "partial",
                "child_references_excluded": sum(b.get("type") in references for b in visible),
                "targets_total": len(block_ids) + 1, "targets_checked": successful, "errors": errors}, {"comment:" + cid for cid in comments}

    async def _page_snapshot(self, page: Dict, db_id=None, db_title=None):
        page_id = page["id"]
        blocks = await self.get_blocks(page_id)
        content = await self.get_page_content(page_id, blocks=blocks)
        properties = self.extract_properties(await self._complete_properties(page))
        title = next((self.extract_text_from_rich_text(p.get("title", []))
                      for p in page.get("properties", {}).values() if p.get("type") == "title"), "")
        title = self.pii_filter.filter_content(title) or f"Page {page_id[:8]}"
        author = await self._author(page.get("created_by", {}))
        editor = await self._author(page.get("last_edited_by", {}))
        page_url = page.get("url") or f"https://www.notion.so/{page_id.replace('-', '')}"
        metadata = {"page_id": page_id, "page_title": title, "author": author.get("name"),
                    "author_id": author.get("id"), "last_edited_by": editor.get("name"),
                    "published_at": page.get("created_time"), "published_confidence": 0.85,
                    "last_modified": page.get("last_edited_time"), "created_time": page.get("created_time"),
                    "last_edited_time": page.get("last_edited_time"), "record_kind": "page",
                    "is_private": self.is_private, "access_source": self.access_source,
                    "workspace_id": self.workspace_id, "database_id": db_id,
                    "database_title": self.pii_filter.filter_content(db_title) if db_title else None,
                    "page_url": page_url, "url": page_url, "source_url": page_url, "properties": properties}
        metadata["comment_coverage"], observed_comments = await self._comment_snapshot(page, blocks, metadata)
        self._queue_document({"source": "notion", "source_type": "notion", "title": title,
                              "content": content, "url": page_url, "metadata": metadata,
                              "rid": str(NotionPageRID(self.workspace_id, page_id)), "state_key": page_id})
        return metadata["comment_coverage"], observed_comments

    def extract_text_from_block(self, block: Dict) -> Optional[str]:
        """Extract text content from a Notion block"""
        block_type = block.get("type")
        if not block_type:
            return None

        block_data = block.get(block_type, {})

        # Handle text-based blocks
        text_types = [
            "paragraph", "heading_1", "heading_2", "heading_3",
            "bulleted_list_item", "numbered_list_item", "to_do",
            "toggle", "quote", "callout"
        ]

        if block_type in text_types:
            rich_text = block_data.get("rich_text", [])
            return self.extract_text_from_rich_text(rich_text)

        # Handle code blocks
        elif block_type == "code":
            rich_text = block_data.get("rich_text", [])
            language = block_data.get("language", "")
            code = self.extract_text_from_rich_text(rich_text)
            return f"```{language}\n{code}\n```" if code else None

        # Handle tables
        elif block_type == "table":
            return "[Table]"

        # Handle dividers
        elif block_type == "divider":
            return "---"

        # Handle video blocks - extract URL for reference
        elif block_type == "video":
            video_type = block_data.get("type", "")
            caption = self.extract_text_from_rich_text(block_data.get("caption", []))
            if video_type == "external":
                url = block_data.get("external", {}).get("url", "")
                return f"[Video: {url}]" + (f" - {caption}" if caption else "")
            elif video_type == "file":
                # File URLs are temporary S3 signed URLs - note this for reference
                url = block_data.get("file", {}).get("url", "")
                # Extract a cleaner reference (the URL will expire)
                return f"[Video Recording]" + (f" - {caption}" if caption else "")
            return "[Video]"

        # Handle embed blocks (YouTube, Loom, etc.)
        elif block_type == "embed":
            url = block_data.get("url", "")
            caption = self.extract_text_from_rich_text(block_data.get("caption", []))
            if url:
                return f"[Embed: {url}]" + (f" - {caption}" if caption else "")
            return "[Embed]"

        # Handle bookmark blocks
        elif block_type == "bookmark":
            url = block_data.get("url", "")
            caption = self.extract_text_from_rich_text(block_data.get("caption", []))
            if url:
                return f"[Link: {url}]" + (f" - {caption}" if caption else "")
            return "[Bookmark]"

        # Handle audio blocks
        elif block_type == "audio":
            audio_type = block_data.get("type", "")
            caption = self.extract_text_from_rich_text(block_data.get("caption", []))
            if audio_type == "external":
                url = block_data.get("external", {}).get("url", "")
                return f"[Audio: {url}]" + (f" - {caption}" if caption else "")
            return "[Audio Recording]" + (f" - {caption}" if caption else "")

        # Handle file blocks
        elif block_type == "file":
            file_type = block_data.get("type", "")
            caption = self.extract_text_from_rich_text(block_data.get("caption", []))
            name = block_data.get("name", "")
            if file_type == "external":
                url = block_data.get("external", {}).get("url", "")
                return f"[File: {name or url}]" + (f" - {caption}" if caption else "")
            return f"[File: {name}]" if name else "[File]"

        # Handle PDF blocks
        elif block_type == "pdf":
            pdf_type = block_data.get("type", "")
            caption = self.extract_text_from_rich_text(block_data.get("caption", []))
            if pdf_type == "external":
                url = block_data.get("external", {}).get("url", "")
                return f"[PDF: {url}]" + (f" - {caption}" if caption else "")
            return "[PDF Document]" + (f" - {caption}" if caption else "")

        # Handle image blocks - reference but don't include binary
        elif block_type == "image":
            caption = self.extract_text_from_rich_text(block_data.get("caption", []))
            image_type = block_data.get("type", "")
            if image_type == "external":
                url = block_data.get("external", {}).get("url", "")
                return f"[Image: {url}]" + (f" - {caption}" if caption else "")
            return "[Image]" + (f" - {caption}" if caption else "")

        # Handle link preview blocks
        elif block_type == "link_preview":
            url = block_data.get("url", "")
            return f"[Link Preview: {url}]" if url else "[Link Preview]"

        return None
    
    def extract_text_from_rich_text(self, rich_text: List[Dict]) -> str:
        """Extract plain text from Notion rich text array"""
        text_parts = []
        for text_obj in rich_text:
            if "plain_text" in text_obj:
                text_parts.append(text_obj["plain_text"])
            elif text_obj.get("type") == "text":
                text_parts.append(text_obj.get("text", {}).get("content", ""))
        return "".join(text_parts)
    
    def extract_properties(self, properties: Dict) -> Dict[str, Any]:
        """Extract key-value pairs from Notion properties, with PII filtering"""
        extracted = {}

        for prop_name, prop_data in properties.items():
            prop_type = prop_data.get("type")

            # Skip PII property types if filter is enabled
            if self.pii_filter.should_skip_property(prop_type):
                continue

            if prop_type == "title":
                title_text = self.extract_text_from_rich_text(
                    prop_data.get("title", [])
                )
                if title_text:
                    extracted[prop_name] = title_text

            elif prop_type == "rich_text":
                text = self.extract_text_from_rich_text(
                    prop_data.get("rich_text", [])
                )
                if text:
                    # Apply PII filtering to rich text content
                    extracted[prop_name] = self.pii_filter.filter_content(text)

            elif prop_type == "number":
                extracted[prop_name] = prop_data.get("number")

            elif prop_type == "select":
                select = prop_data.get("select")
                if select:
                    extracted[prop_name] = select.get("name")

            elif prop_type == "status":
                extracted[prop_name] = (prop_data.get("status") or {}).get("name")

            elif prop_type == "people":
                people = [self._safe_person(user) for user in prop_data.get("people", [])]
                extracted[prop_name] = sorted(people, key=lambda user: user.get("id", ""))

            elif prop_type == "relation":
                extracted[prop_name] = sorted({item["id"] for item in prop_data.get("relation", []) if item.get("id")})

            elif prop_type == "multi_select":
                options = prop_data.get("multi_select", [])
                if options:
                    extracted[prop_name] = [opt.get("name") for opt in options]

            elif prop_type == "date":
                date_obj = prop_data.get("date")
                if date_obj:
                    extracted[prop_name] = date_obj.get("start")

            elif prop_type == "checkbox":
                extracted[prop_name] = prop_data.get("checkbox", False)

            elif prop_type == "url":
                extracted[prop_name] = prop_data.get("url")

            elif prop_type == "email":
                # PII: Skip email properties (handled by should_skip_property)
                pass

            elif prop_type == "phone_number":
                # PII: Skip phone properties (handled by should_skip_property)
                pass

        # Property titles/names/selects/URLs can also contain contact information.
        def redact(value):
            if isinstance(value, str):
                return self.pii_filter.filter_content(value)
            if isinstance(value, list):
                return [redact(v) for v in value]
            if isinstance(value, dict):
                return {k: (v if k == "id" else redact(v)) for k, v in value.items()}
            return value
        return {self.pii_filter.filter_content(k): (v if properties[k].get("type") == "relation" else redact(v))
                for k, v in extracted.items()}

    async def monitor_database(self, database_id: str, 
                              check_interval: int = 3600,
                              priority: str = "medium"):
        """Add a database to monitor for changes"""
        # Get database info
        db_info = await self.get_database(database_id)
        if not db_info:
            print(f"❌ Could not add database {database_id} to monitoring")
            return
        
        title = self.extract_text_from_rich_text(
            db_info.get("title", [])
        ) or f"Database {database_id[:8]}"
        
        self.monitored_databases[database_id] = {
            "title": title,
            "check_interval": check_interval,
            "priority": priority,
            "last_checked": None,
            "url": db_info.get("url", "")
        }
        
        print(f"✅ Monitoring database: {title}")
    
    async def check_for_changes(self) -> List[Dict]:
        """Reconcile a durable fair queue, independent of page edit timestamps."""
        now = datetime.now(timezone.utc)
        candidates = {}
        database_pages = self._poll_state("notion_database_pages_v1")
        coverage = self._poll_state("notion_poll_coverage_v1")
        for db_id, info in self.monitored_databases.items():
            last = info.get("last_checked")
            if not last or now - last >= timedelta(seconds=info["check_interval"]):
                try:
                    # Full discovery: comments need not update page last_edited_time.
                    pages = await self.query_database(db_id)
                    if any(not p.get("id") for p in pages):
                        raise NotionFetchError(f"databases/{db_id}/query", code="missing_page_id")
                    database_pages[db_id] = sorted({p["id"] for p in pages})
                    for page in pages:
                        candidates[page["id"]] = (page, db_id, info["title"])
                    info["last_checked"] = now
                    coverage["database:" + db_id] = {"status": "observed"}
                except NotionFetchError as exc:
                    coverage["database:" + db_id] = {"status": "incomplete", "error": exc.coverage(), "deletion_inferred": False}
            # Persist IDs only, not raw page/property/user objects. Between discovery
            # passes, fetch fresh metadata for the next pages in the scan queue.
            for page_id in database_pages.get(db_id, []):
                candidates.setdefault(page_id, (None, db_id, info["title"]))
        for page_id in self.monitored_pages:
            candidates.setdefault(page_id, (None, None, None))
        ids = {pid for pid in candidates if pid not in self.skip_pages and pid.replace('-', '') not in self.skip_pages}
        cursor = self._poll_state("notion_page_cursor_v1")
        queue = [pid for pid in cursor.get("queue", []) if pid in ids]
        queued = set(queue)
        queue.extend(sorted(ids - queued))
        selected = queue[:self.max_pages_per_poll]
        cursor["queue"] = queue[len(selected):] + selected
        eligible = set()
        for page_id in selected:
            page, db_id, title = candidates[page_id]
            try:
                if page is None:
                    page = await self.get_page(page_id, strict=True)
                if not page or page.get("archived") or page.get("in_trash"):
                    coverage[page_id] = {"status": "unavailable", "deletion_inferred": False}
                    continue
                comment_coverage, observed_comments = await self._page_snapshot(page, db_id, title)
                coverage[page_id] = {"status": "observed", "comments": comment_coverage}
                eligible.add(page["id"])
                # Retry only comments positively re-observed. A skipped, denied or
                # absent target keeps its pending record without publishing stale text.
                eligible.update(observed_comments)
            except NotionFetchError as exc:
                coverage[page_id] = {"status": "incomplete", "error": exc.coverage(), "deletion_inferred": False}
                print(f"⚠️ {exc}")
        self.state.save()  # Outbox and scan queue survive coordinator failures/restarts.
        return [doc for key, doc in self._poll_state("notion_outbox_v1").items() if key in eligible]

    async def send_to_coordinator(self, changes: List[Dict]):
        """Send changes to KOI coordinator"""
        print(f"📤 Sending {len(changes)} changes to coordinator...")
        
        for i, change in enumerate(changes, 1):
            state_key = None
            try:
                print(f"   [{i}/{len(changes)}] Processing {change.get('title', 'Unknown')}...")
                state_key = change.get("state_key") or change.get("metadata", {}).get("page_id") or change.get("rid")
                state_source = change.get("state_source") or self.workspace_id
                if state_key:
                    self.state.mark_pending(state_source, state_key)
                
                # Create bundle from document
                print(f"   Creating bundle for RID: {change.get('rid', 'unknown')}")
                bundle = document_to_bundle(change)
                print(f"   Bundle created successfully: {bundle.rid}")
                
                # Send to coordinator using the appropriate method based on event type
                event_type = change["event_type"]
                print(f"   Emitting {event_type} event...")
                
                if event_type == "NEW":
                    success = await self.koi_node.emit_new_event(bundle)
                elif event_type == "UPDATE":
                    success = await self.koi_node.emit_update_event(bundle)
                else:
                    # For other event types like FORGET
                    success = await self.koi_node.emit_forget_event(bundle.rid, reason="Content removed")
                
                if success:
                    if state_key:
                        self.state.mark_processed(state_source, state_key)
                    content_hash = change.get("content_hash")
                    if content_hash:
                        self._poll_state("notion_document_hashes_v1")[state_key] = content_hash
                    outbox = self._poll_state("notion_outbox_v1")
                    if outbox.get(state_key, {}).get("content_hash") == content_hash:
                        outbox.pop(state_key, None)
                    self.state.save()
                    print(f"   ✅ Sent to coordinator: {change['rid']}")
                else:
                    if state_key:
                        self.state.clear_pending(state_source, state_key)
                    print(f"   ❌ Failed to send event: {change['rid']}")
                
            except Exception as e:
                import traceback
                if state_key:
                    self.state.clear_pending(state_source, state_key)
                print(f"   ❌ Failed to send event: {e}")
                print(f"   Traceback: {traceback.format_exc()}")
            finally:
                self.state.save()

    async def send_heartbeat_event(self, response_to: Optional[str] = None):
        """Send a heartbeat event to register with coordinator

        Args:
            response_to: Optional RID to respond to for ping requests
        """
        try:
            # Create a heartbeat bundle
            # Debug: log what we're monitoring
            db_count = len(self.monitored_databases)
            page_count = len(self.monitored_pages)
            print(f"📊 Heartbeat: Monitoring {db_count} databases, {page_count} pages")

            # Build monitoring list
            monitoring_list = []
            for db_id, db in self.monitored_databases.items():
                url = db.get('url', db_id)
                monitoring_list.append(url)
                print(f"   DB: {url}")
            for page_id, page in self.monitored_pages.items():
                url = page.get('url', page_id)
                monitoring_list.append(url)
                if len(monitoring_list) <= 5:  # Show first 5 for debugging
                    print(f"   Page: {url}")

            # Use fallback if empty
            if not monitoring_list:
                monitoring_list = ["Notion workspace"]

            # Send all pages to monitoring but summarize for display
            total_count = len(monitoring_list)
            if total_count > 100:
                # Keep first 100 for display but add a summary
                display_list = monitoring_list[:100]
                display_list.append(f"... and {total_count - 100} more pages")
                print(f"   Monitoring {total_count} total pages (showing first 100 in dashboard)")
                monitoring_list = display_list

            print(f"   Final monitoring list has {len(monitoring_list)} items")

            heartbeat_data = {
                "type": "sensor_heartbeat",
                "sensor_id": self.node_id,
                "sensor_type": "notion",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "active",
                "monitoring": monitoring_list
            }

            # Add response_to if this is a ping response
            if response_to:
                heartbeat_data["response_to"] = response_to

            # Create document for heartbeat with required fields
            heartbeat_document = {
                'id': f"notion_heartbeat_{self.node_id}_{int(datetime.now().timestamp())}",
                'title': f'Notion Sensor Heartbeat - {self.node_id}',
                'url': '',
                'type': 'heartbeat',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'content': json.dumps(heartbeat_data),
                'metadata': {
                    'sensor_type': 'notion',
                    'sensor_id': self.node_id,
                    'event_type': 'HEARTBEAT'
                }
            }

            # Convert to bundle and emit
            bundle = document_to_bundle(heartbeat_document)
            await self.koi_node.emit_new_event(bundle)

            if response_to:
                print(f"📡 Sent ping response heartbeat to coordinator (responding to {response_to})")
            else:
                print("📡 Sent heartbeat event to register with coordinator")

        except Exception as e:
            print(f"❌ Error sending heartbeat: {e}")

    async def send_periodic_heartbeats(self):
        """Send periodic heartbeats every 30 minutes"""
        while True:
            try:
                await asyncio.sleep(1800)  # 30 minutes
                await self.send_heartbeat_event()
                print("💓 Sent periodic heartbeat")
            except asyncio.CancelledError:
                print("🛑 Periodic heartbeat task cancelled")
                break
            except Exception as e:
                print(f"❌ Error in periodic heartbeat: {e}")

    async def handle_coordinator_events(self):
        """Listen for and handle coordinator events like ping requests"""
        while True:
            try:
                # Check for coordinator events
                # TODO: KOIPartialNode doesn't have poll_coordinator_events method
                # For now, just skip this until proper implementation
                events = []

                for event in events:
                    event_type = event.get('event_type')

                    if event_type == 'PING_REQUEST':
                        # Check if ping is for this sensor
                        target_sensor = event.get('target_sensor')
                        if target_sensor == self.node_id or target_sensor == 'notion':
                            print(f"📡 Received ping request: {event.get('rid')}")
                            # Respond with heartbeat
                            await self.send_heartbeat_event(response_to=event.get('rid'))

                await asyncio.sleep(30)  # Check every 30 seconds

            except asyncio.CancelledError:
                print("🛑 Coordinator event handler cancelled")
                break
            except Exception as e:
                print(f"❌ Error handling coordinator events: {e}")
                await asyncio.sleep(30)

    async def run_monitoring_loop(self, poll_interval: int = 1800):
        """Main monitoring loop

        Args:
            poll_interval: Seconds between polling cycles (default 30 minutes)
        """
        print(f"🚀 Starting Notion monitoring loop...")
        print(f"⏰ Polling interval: {poll_interval} seconds ({poll_interval/60:.1f} minutes)")

        # Send startup heartbeat to register with coordinator
        await self.send_heartbeat_event()

        # Start background tasks for periodic heartbeats and coordinator event handling
        heartbeat_task = asyncio.create_task(self.send_periodic_heartbeats())
        coordinator_task = asyncio.create_task(self.handle_coordinator_events())

        while True:
            try:
                # Check for changes
                changes = await self.check_for_changes()

                if changes:
                    print(f"📊 Found {len(changes)} changes")
                    await self.send_to_coordinator(changes)
                else:
                    print(f"✅ No changes found")

                # Wait before next check
                print(f"⏰ Next check in {poll_interval} seconds ({poll_interval/60:.1f} minutes)")
                await asyncio.sleep(poll_interval)

            except KeyboardInterrupt:
                print("\n🛑 Received interrupt signal, shutting down...")
                break
            except Exception as e:
                print(f"❌ Error in monitoring loop: {e}")
                print(f"⏰ Retrying in {poll_interval} seconds...")
                await asyncio.sleep(poll_interval)


async def main():
    """Main entry point with continuous monitoring"""
    print("🚀 Notion sensor starting...")
    import os
    from dotenv import load_dotenv

    # Load environment variables
    load_dotenv()
    print("✓ Environment loaded")

    # Get Notion token from environment
    notion_token = os.getenv('NOTION_API_KEY')
    if not notion_token:
        print("❌ NOTION_API_KEY not found in environment variables")
        return

    # Get polling interval (default 30 minutes)
    poll_interval = int(os.getenv('NOTION_POLL_INTERVAL', 1800))

    # Privacy settings for regen_main workspace per config.yaml — must be
    # threaded explicitly because this bootstrap path doesn't load the YAML.
    # Defaults (is_private=False) would leak private docs to unauth queries.
    async with NotionKOISensor(
        notion_token=notion_token,
        workspace_id="regen",
        is_private=True,
        access_source="notion-main-workspace",
    ) as sensor:
        print("\n🔍 Searching Notion workspace...")

        # Search for all content
        all_items = await sensor.search_workspace()

        print(f"\n📊 Found {len(all_items)} items in workspace:")

        databases = []
        pages = []

        # Process items without printing each one
        for item in all_items:
            if item["object"] == "database":
                databases.append(item)
                title = sensor.extract_text_from_rich_text(
                    item.get("title", [])
                ) or f"Database {item['id'][:8]}"
                print(f"   📁 Database: {title}")
            elif item["object"] == "page":
                pages.append(item)

        # Print summary of pages instead of each one
        if pages:
            print(f"   📄 Found {len(pages)} pages")
            # Show first few as examples
            for page in pages[:5]:
                print(f"      • {page.get('url', page['id'][:8])}")
            if len(pages) > 5:
                print(f"      ... and {len(pages) - 5} more")

        print(f"\nSummary: {len(databases)} databases, {len(pages)} pages")

        # Monitor all databases found
        if databases:
            for db in databases:
                await sensor.monitor_database(db["id"])

        # Track pages for reporting (even if not actively monitoring)
        if pages:
            for page in pages:
                page_id = page.get('id', '')
                page_url = page.get('url', f"https://notion.so/{page_id}")
                page_title = "Untitled"

                # Try to extract title from properties
                if 'properties' in page:
                    for prop_name, prop_value in page['properties'].items():
                        if prop_value.get('type') == 'title' and prop_value.get('title'):
                            page_title = ''.join(t['plain_text'] for t in prop_value['title'])
                            break

                sensor.monitored_pages[page_id] = {
                    'id': page_id,
                    'url': page_url,
                    'title': page_title,
                    'last_checked': datetime.now(timezone.utc).isoformat()
                }

        # Start continuous monitoring if we have databases or pages
        if databases or pages:
            print(f"\n📊 Before starting monitoring loop:")
            print(f"   Monitored databases: {len(sensor.monitored_databases)}")
            print(f"   Monitored pages: {len(sensor.monitored_pages)}")
            if sensor.monitored_pages:
                # Show first few pages as example
                for i, (page_id, page_info) in enumerate(list(sensor.monitored_pages.items())[:3]):
                    print(f"   Example page {i+1}: {page_info.get('url', page_id)}")
            await sensor.run_monitoring_loop(poll_interval)
        else:
            print("\n⚠️ No databases or pages found to monitor")


if __name__ == "__main__":
    print("Starting Notion sensor...")
    asyncio.run(main())
