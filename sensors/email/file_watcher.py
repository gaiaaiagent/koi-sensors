#!/usr/bin/env python3
"""
File Watcher for Email Sensor
Watches Maildir for new emails and triggers processing
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import List, Optional, Set
import time

logger = logging.getLogger(__name__)

# Check for watchdog availability
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    logger.warning("watchdog not installed - file watching disabled")


class EmailFileHandler(FileSystemEventHandler):
    """
    Handle Maildir file events.

    Tracks new/modified email files and queues them for processing.
    Uses debouncing to avoid processing the same file multiple times
    when it's being written.
    """

    def __init__(
        self,
        sensor,
        debounce_seconds: float = 5.0,
    ):
        """
        Initialize handler.

        Args:
            sensor: EmailSensor instance
            debounce_seconds: Wait time before processing new files
        """
        super().__init__()
        self.sensor = sensor
        self.debounce_seconds = debounce_seconds

        # Track pending files with their first-seen time
        self._pending: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def on_created(self, event):
        """Handle file creation."""
        if event.is_directory:
            return

        # Only process files in cur/ or new/ directories
        path = Path(event.src_path)
        if path.parent.name not in ('cur', 'new'):
            return

        # Skip hidden files
        if path.name.startswith('.'):
            return

        logger.debug(f"File created: {event.src_path}")
        self._schedule_processing(event.src_path)

    def on_modified(self, event):
        """Handle file modification."""
        if event.is_directory:
            return

        path = Path(event.src_path)
        if path.parent.name not in ('cur', 'new'):
            return

        if path.name.startswith('.'):
            return

        logger.debug(f"File modified: {event.src_path}")
        self._schedule_processing(event.src_path)

    def _schedule_processing(self, file_path: str):
        """Schedule file for processing after debounce period."""
        now = time.time()
        self._pending[file_path] = now

    async def process_pending(self):
        """Process files that have passed the debounce period."""
        now = time.time()
        to_process = []

        async with self._lock:
            for path, first_seen in list(self._pending.items()):
                if now - first_seen >= self.debounce_seconds:
                    to_process.append(path)
                    del self._pending[path]

        for path in to_process:
            try:
                logger.info(f"Processing new email: {Path(path).name}")
                rid = await self.sensor.process_single_file(path)
                if rid:
                    logger.info(f"✅ Processed: {rid}")
                else:
                    logger.debug(f"Skipped or failed: {path}")
            except Exception as e:
                logger.error(f"Error processing {path}: {e}")

    def get_pending_count(self) -> int:
        """Get count of pending files."""
        return len(self._pending)


class EmailFileWatcher:
    """
    Watch Maildir directories for new emails.

    Uses watchdog for filesystem events and processes new emails
    in real-time.
    """

    def __init__(
        self,
        sensor,
        watch_paths: Optional[List[str]] = None,
        debounce_seconds: float = 5.0,
        poll_interval: float = 1.0,
    ):
        """
        Initialize file watcher.

        Args:
            sensor: EmailSensor instance
            watch_paths: List of paths to watch (defaults to INBOX)
            debounce_seconds: Debounce time for new files
            poll_interval: How often to check for ready files
        """
        if not WATCHDOG_AVAILABLE:
            raise ImportError("watchdog required for file watching")

        self.sensor = sensor
        self.debounce_seconds = debounce_seconds
        self.poll_interval = poll_interval

        # Default watch paths
        if watch_paths is None:
            base_path = sensor.maildir.base_path
            watch_paths = [
                str(base_path / "INBOX"),
            ]

        # Expand paths
        self.watch_paths = [
            Path(os.path.expanduser(p)) for p in watch_paths
        ]

        self._observer: Optional[Observer] = None
        self._handler: Optional[EmailFileHandler] = None
        self._running = False

    async def start(self):
        """Start watching for file changes."""
        self._handler = EmailFileHandler(
            self.sensor,
            debounce_seconds=self.debounce_seconds,
        )

        self._observer = Observer()

        for path in self.watch_paths:
            if path.exists():
                logger.info(f"Watching: {path}")
                self._observer.schedule(
                    self._handler,
                    str(path),
                    recursive=True,
                )
            else:
                logger.warning(f"Watch path does not exist: {path}")

        self._observer.start()
        self._running = True

        logger.info(f"File watcher started, watching {len(self.watch_paths)} paths")

    async def stop(self):
        """Stop watching."""
        self._running = False

        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None

        logger.info("File watcher stopped")

    async def run(self):
        """Run the watcher loop."""
        await self.start()

        try:
            while self._running:
                # Process any files that are ready
                if self._handler:
                    await self._handler.process_pending()

                await asyncio.sleep(self.poll_interval)

        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()


async def main():
    """Run file watcher as standalone process."""
    import argparse
    import yaml

    # Add parent paths
    sys.path.insert(0, str(Path(__file__).parent))

    from email_sensor import EmailSensor

    parser = argparse.ArgumentParser(description='Email File Watcher')
    parser.add_argument('--config', type=str, help='Path to config.yaml')

    args = parser.parse_args()

    # Load config
    config_path = args.config or Path(__file__).parent / "config.yaml"
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    # Get watch paths from config
    watch_config = config.get('file_watcher', {})
    if not watch_config.get('enabled', True):
        logger.error("File watcher is disabled in config")
        return

    watch_paths = watch_config.get('watch_paths', [])
    debounce = watch_config.get('debounce', 5)

    # Create sensor
    sensor = EmailSensor(config_path=str(config_path))

    # Setup signal handlers
    stop_event = asyncio.Event()

    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, stopping...")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create and run watcher
    watcher = EmailFileWatcher(
        sensor,
        watch_paths=watch_paths,
        debounce_seconds=debounce,
    )

    logger.info("Starting file watcher...")

    try:
        # Connect sensor
        await sensor.connect()
        await sensor.embedder.__aenter__()

        # Start watcher
        await watcher.start()

        # Wait for stop signal
        await stop_event.wait()

    finally:
        await watcher.stop()
        await sensor.embedder.__aexit__(None, None, None)
        await sensor.close()


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    asyncio.run(main())
