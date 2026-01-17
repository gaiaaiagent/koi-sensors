#!/usr/bin/env python3
"""
KOI Obsidian Sensor - Monitor local Obsidian vault for changes
Parses YAML frontmatter and extracts wikilinks as relationships
"""

import asyncio
import hashlib
import re
import yaml
from typing import Dict, List, Any, Optional, Set
from datetime import datetime, timezone
from pathlib import Path
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent, FileDeletedEvent

# KOI Protocol imports
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.rid_system import ORN
from koi_protocol.core.bundle_system import Bundle, document_to_bundle
from shared.persistent_state import PersistentSensorState


class ObsidianNoteRID(ORN):
    """Obsidian note RID: orn:obsidian.note:vault/path/to/note"""
    namespace = "obsidian.note"

    def __init__(self, vault_name: str, note_path: str):
        self.vault_name = vault_name
        # Normalize path: remove .md extension, use forward slashes
        self.note_path = note_path.replace('.md', '').replace('\\', '/')
        super().__init__()

    @property
    def reference(self) -> str:
        return f"{self.vault_name}/{self.note_path}"


class ObsidianEntityRID(ORN):
    """Obsidian entity RID for schema.org typed entities: orn:obsidian.entity:vault/type/id"""
    namespace = "obsidian.entity"

    def __init__(self, vault_name: str, entity_type: str, entity_id: str):
        self.vault_name = vault_name
        self.entity_type = entity_type.replace('schema:', '')  # Remove schema: prefix
        self.entity_id = entity_id
        super().__init__()

    @property
    def reference(self) -> str:
        return f"{self.vault_name}/{self.entity_type}/{self.entity_id}"


class YAMLFrontmatterParser:
    """Parse YAML frontmatter and extract schema.org typed entities"""

    FRONTMATTER_PATTERN = re.compile(r'^---\s*\n(.*?)\n---', re.DOTALL)
    WIKILINK_PATTERN = re.compile(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]')

    @classmethod
    def parse_note(cls, content: str) -> Dict[str, Any]:
        """
        Parse a note and extract frontmatter + body

        Returns:
            {
                'frontmatter': dict or None,
                'body': str,
                'wikilinks': list of linked note names,
                'entity_type': str or None (e.g., 'Person', 'Organization'),
                'entity_id': str or None
            }
        """
        result = {
            'frontmatter': None,
            'body': content,
            'wikilinks': [],
            'entity_type': None,
            'entity_id': None
        }

        # Extract frontmatter
        match = cls.FRONTMATTER_PATTERN.match(content)
        if match:
            try:
                frontmatter_text = match.group(1)
                # Quote keys starting with @ (YAML reserved character)
                # Convert "@id: value" to '"@id": value'
                frontmatter_text = re.sub(
                    r'^(@\w+)(\s*:)',
                    r'"\1"\2',
                    frontmatter_text,
                    flags=re.MULTILINE
                )
                result['frontmatter'] = yaml.safe_load(frontmatter_text)
                result['body'] = content[match.end():].strip()

                # Extract entity type and ID
                if result['frontmatter']:
                    fm = result['frontmatter']

                    # Get @type (schema.org type)
                    entity_type = fm.get('@type') or fm.get('type')
                    if entity_type:
                        # Normalize: schema:Person -> Person
                        result['entity_type'] = entity_type.replace('schema:', '')

                    # Get @id or generate from name
                    entity_id = fm.get('@id') or fm.get('id')
                    if entity_id:
                        result['entity_id'] = entity_id
                    elif fm.get('name'):
                        # Generate ID from name
                        name = fm.get('name')
                        result['entity_id'] = name.lower().replace(' ', '-')

            except yaml.YAMLError as e:
                print(f"Failed to parse YAML frontmatter: {e}")

        # Extract wikilinks from entire content
        result['wikilinks'] = cls.WIKILINK_PATTERN.findall(content)

        return result

    @classmethod
    def extract_relationships(cls, parsed_note: Dict[str, Any], note_path: str) -> List[Dict[str, str]]:
        """
        Extract relationships from a parsed note

        Returns list of relationship dicts:
        {
            'source': source entity/note,
            'target': target entity/note,
            'relationship_type': type of relationship
        }
        """
        relationships = []

        # Wikilinks as relationships
        for link in parsed_note.get('wikilinks', []):
            relationships.append({
                'source': note_path,
                'target': link,
                'relationship_type': 'mentions'
            })

        # Extract typed relationships from frontmatter
        fm = parsed_note.get('frontmatter') or {}

        # Affiliation relationship
        if 'affiliation' in fm and fm['affiliation']:
            affiliations = fm['affiliation'] if isinstance(fm['affiliation'], list) else [fm['affiliation']]
            for aff in affiliations:
                if aff:
                    relationships.append({
                        'source': note_path,
                        'target': str(aff),
                        'relationship_type': 'affiliatedWith'
                    })

        # Attendees relationship (for meetings)
        if 'attendees' in fm and fm['attendees']:
            for attendee in fm['attendees']:
                if attendee:
                    relationships.append({
                        'source': note_path,
                        'target': str(attendee),
                        'relationship_type': 'hasAttendee'
                    })

        # Project relationship
        if 'project' in fm and fm['project']:
            relationships.append({
                'source': note_path,
                'target': str(fm['project']),
                'relationship_type': 'relatedToProject'
            })

        return relationships


class VaultWatcher(FileSystemEventHandler):
    """Watch vault directory for file changes"""

    def __init__(self, sensor: 'ObsidianSensor'):
        self.sensor = sensor
        self._event_queue: asyncio.Queue = None
        self._loop = None

    def set_event_queue(self, queue: asyncio.Queue, loop):
        self._event_queue = queue
        self._loop = loop

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.md'):
            if self._event_queue and self._loop:
                self._loop.call_soon_threadsafe(
                    self._event_queue.put_nowait,
                    ('modified', event.src_path)
                )

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.md'):
            if self._event_queue and self._loop:
                self._loop.call_soon_threadsafe(
                    self._event_queue.put_nowait,
                    ('created', event.src_path)
                )

    def on_deleted(self, event):
        if not event.is_directory and event.src_path.endswith('.md'):
            if self._event_queue and self._loop:
                self._loop.call_soon_threadsafe(
                    self._event_queue.put_nowait,
                    ('deleted', event.src_path)
                )


class ObsidianSensor:
    """
    KOI Obsidian Sensor

    Monitors an Obsidian vault for changes and emits KOI bundles
    for notes with YAML frontmatter.
    """

    def __init__(self,
                 node_id: str,
                 coordinator_url: str,
                 vault_path: str,
                 vault_name: str = None,
                 watch_mode: bool = True,
                 schema_types: List[str] = None,
                 exclude_folders: List[str] = None):
        """
        Initialize Obsidian sensor.

        Args:
            node_id: Unique identifier for this sensor
            coordinator_url: KOI coordinator URL
            vault_path: Path to Obsidian vault
            vault_name: Name for the vault (defaults to folder name)
            watch_mode: If True, watch for changes. If False, do one-time scan.
            schema_types: List of schema.org types to track (e.g., ['Person', 'Organization'])
                         If None, tracks all types found.
            exclude_folders: Folders to exclude (e.g., ['.obsidian', '.trash'])
        """
        self.node_id = node_id
        self.coordinator_url = coordinator_url
        self.vault_path = Path(vault_path).expanduser().resolve()
        self.vault_name = vault_name or self.vault_path.name
        self.watch_mode = watch_mode
        self.schema_types = set(schema_types) if schema_types else None
        self.exclude_folders = set(exclude_folders or ['.obsidian', '.trash', '.smart-env', '.claude'])

        if not self.vault_path.exists():
            raise ValueError(f"Vault path does not exist: {self.vault_path}")

        # Initialize KOI node
        self.koi_node = KOIPartialNode(
            node_name="obsidian-sensor",
            coordinator_url=self.coordinator_url,
            poll_interval=30
        )

        # Persistent state for tracking processed notes
        self.state = PersistentSensorState('obsidian', Path(__file__).parent)

        # File watcher
        self.watcher = VaultWatcher(self)
        self.observer = None
        self._event_queue = None

        print(f"📓 KOI Obsidian Sensor initialized")
        print(f"   Node ID: {self.node_id}")
        print(f"   Coordinator: {self.coordinator_url}")
        print(f"   Vault: {self.vault_path}")
        print(f"   Vault Name: {self.vault_name}")
        print(f"   Watch Mode: {self.watch_mode}")
        if self.schema_types:
            print(f"   Tracking Types: {', '.join(self.schema_types)}")
        print(f"   Excluded Folders: {', '.join(self.exclude_folders)}")

    def _should_process_file(self, file_path: Path) -> bool:
        """Check if a file should be processed"""
        # Check excluded folders
        for part in file_path.parts:
            if part in self.exclude_folders:
                return False

        # Must be markdown
        if file_path.suffix != '.md':
            return False

        return True

    def _get_relative_path(self, file_path: Path) -> str:
        """Get path relative to vault root"""
        return str(file_path.relative_to(self.vault_path))

    def _compute_content_hash(self, content: str) -> str:
        """Compute hash of content for change detection"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]

    async def _process_note(self, file_path: Path) -> Optional[Bundle]:
        """Process a single note and create a KOI bundle"""
        if not self._should_process_file(file_path):
            return None

        try:
            content = file_path.read_text(encoding='utf-8')
        except Exception as e:
            print(f"❌ Failed to read {file_path}: {e}")
            return None

        # Parse the note
        parsed = YAMLFrontmatterParser.parse_note(content)

        # Check if we should track this type
        if self.schema_types and parsed['entity_type']:
            if parsed['entity_type'] not in self.schema_types:
                return None

        relative_path = self._get_relative_path(file_path)
        content_hash = self._compute_content_hash(content)

        # Check if content has changed
        stored_hash = self.state.get(f"hash:{relative_path}")
        if stored_hash == content_hash:
            return None  # No change

        # Create RID
        if parsed['entity_type'] and parsed['entity_id']:
            rid = ObsidianEntityRID(
                self.vault_name,
                parsed['entity_type'],
                parsed['entity_id']
            )
        else:
            rid = ObsidianNoteRID(self.vault_name, relative_path)

        # Extract relationships
        relationships = YAMLFrontmatterParser.extract_relationships(parsed, relative_path)

        # Build document
        document = {
            'rid': str(rid),
            'source': 'obsidian',
            'vault': self.vault_name,
            'path': relative_path,
            'title': file_path.stem,
            'content': content,
            'body': parsed['body'],
            'frontmatter': parsed['frontmatter'],
            'entity_type': parsed['entity_type'],
            'entity_id': parsed['entity_id'],
            'wikilinks': parsed['wikilinks'],
            'relationships': relationships,
            'content_hash': content_hash,
            'indexed_at': datetime.now(timezone.utc).isoformat(),
            'modified_at': datetime.fromtimestamp(
                file_path.stat().st_mtime, timezone.utc
            ).isoformat()
        }

        # Create bundle
        bundle = document_to_bundle(document, rid)

        # Update state
        self.state.set(f"hash:{relative_path}", content_hash)

        return bundle

    async def scan_vault(self) -> List[Bundle]:
        """Scan entire vault and return bundles for all notes"""
        print(f"📂 Scanning vault: {self.vault_path}")
        bundles = []

        for file_path in self.vault_path.rglob('*.md'):
            bundle = await self._process_note(file_path)
            if bundle:
                bundles.append(bundle)

        print(f"   Found {len(bundles)} notes to process")
        return bundles

    async def emit_bundle(self, bundle: Bundle, is_update: bool = False):
        """Emit a bundle to the KOI coordinator"""
        try:
            if is_update:
                success = await self.koi_node.emit_update_event(bundle)
            else:
                success = await self.koi_node.emit_new_event(bundle)

            if success:
                print(f"✓ Emitted: {bundle.rid}")
            else:
                print(f"✗ Failed to emit: {bundle.rid}")
        except Exception as e:
            print(f"❌ Error emitting bundle: {e}")

    async def emit_forget(self, file_path: Path):
        """Emit a forget event for a deleted note"""
        relative_path = self._get_relative_path(file_path)
        rid = ObsidianNoteRID(self.vault_name, relative_path)

        try:
            success = await self.koi_node.emit_forget_event(rid, reason="Note deleted")
            if success:
                print(f"✓ Forgot: {rid}")
                self.state.delete(f"hash:{relative_path}")
        except Exception as e:
            print(f"❌ Error forgetting note: {e}")

    async def run(self):
        """Main run loop"""
        await self.koi_node.start()

        try:
            # Initial scan
            bundles = await self.scan_vault()
            for bundle in bundles:
                await self.emit_bundle(bundle)

            if not self.watch_mode:
                print("📓 One-time scan complete")
                return

            # Watch mode
            print(f"👀 Watching for changes in {self.vault_path}")

            self._event_queue = asyncio.Queue()
            loop = asyncio.get_event_loop()
            self.watcher.set_event_queue(self._event_queue, loop)

            self.observer = Observer()
            self.observer.schedule(self.watcher, str(self.vault_path), recursive=True)
            self.observer.start()

            try:
                while True:
                    try:
                        event_type, file_path = await asyncio.wait_for(
                            self._event_queue.get(),
                            timeout=60
                        )

                        file_path = Path(file_path)

                        if event_type == 'deleted':
                            await self.emit_forget(file_path)
                        else:
                            # Small delay to let file settle
                            await asyncio.sleep(0.5)
                            bundle = await self._process_note(file_path)
                            if bundle:
                                await self.emit_bundle(bundle, is_update=(event_type == 'modified'))

                    except asyncio.TimeoutError:
                        # Heartbeat
                        pass

            finally:
                self.observer.stop()
                self.observer.join()

        finally:
            await self.koi_node.stop()


async def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='KOI Obsidian Sensor')
    parser.add_argument('--vault', '-v', required=True, help='Path to Obsidian vault')
    parser.add_argument('--vault-name', '-n', help='Name for the vault')
    parser.add_argument('--coordinator', '-c', default='http://localhost:8005',
                       help='KOI coordinator URL')
    parser.add_argument('--no-watch', action='store_true', help='One-time scan only')
    parser.add_argument('--types', nargs='+', help='Schema types to track (e.g., Person Organization)')

    args = parser.parse_args()

    sensor = ObsidianSensor(
        node_id="obsidian-sensor-1",
        coordinator_url=args.coordinator,
        vault_path=args.vault,
        vault_name=args.vault_name,
        watch_mode=not args.no_watch,
        schema_types=args.types
    )

    await sensor.run()


if __name__ == '__main__':
    asyncio.run(main())
