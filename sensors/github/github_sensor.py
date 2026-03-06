"""
KOI GitHub Sensor - Repository documentation collector
Indexes documentation from GitHub repositories
"""

import asyncio
import aiohttp
import httpx
import json
import logging
import tempfile
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import hashlib
import subprocess
import base64

# Add parent directories to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.rid_system import RID
from koi_protocol.core.bundle_system import Bundle, document_to_bundle
from shared.persistent_state import PersistentSensorState

@dataclass
class GitHubConfig:
    """GitHub sensor configuration"""
    repos: List[Dict[str, Any]]
    coordinator_url: str = "http://localhost:8005"
    source_sensor: str = "github-sensor"
    
    # File patterns to index - comprehensive for full codebase understanding
    file_extensions: List[str] = None

    # Directories to exclude
    excluded_dirs: List[str] = None

    def __post_init__(self):
        if self.file_extensions is None:
            self.file_extensions = [
                # Documentation
                '*.md', '*.MD', '*.mdx',
                '*.rst', '*.txt', '*.asciidoc',
                'README*', 'CHANGELOG*', 'CONTRIBUTING*',
                'LICENSE*', 'COPYRIGHT*', 'NOTICE*',

                # Source Code - Go (CRITICAL for Cosmos SDK)
                '*.go',

                # Source Code - Web/Frontend
                '*.ts', '*.tsx',
                '*.js', '*.jsx',

                # Source Code - Other
                '*.py',
                '*.rs',
                '*.sol',

                # Protocol Buffers (CRITICAL for Cosmos SDK)
                '*.proto',

                # Configuration & Dependencies
                '*.json', '*.yaml', '*.yml',
                '*.toml', '*.ini', '*.cfg',
                'go.mod', 'go.sum',

                # Build & Infrastructure
                'Makefile', 'makefile',
                'Dockerfile*',
                'docker-compose*.yml', 'docker-compose*.yaml',

                # Schemas & Scripts
                '*.sql',
                '*.graphql', '*.gql',
                '*.sh',
            ]
        
        if self.excluded_dirs is None:
            self.excluded_dirs = [
                # Version control
                '.git',

                # Dependencies/packages
                'node_modules', 'vendor', '.venv', 'venv',
                '__pycache__', '.pytest_cache',

                # Build outputs
                'dist', 'build', 'out', 'target', 'bin',
                '_build', '.next',

                # IDE/editor
                '.vscode', '.idea',

                # Test fixtures (usually not useful for understanding)
                'testdata', 'test_fixtures',

                # Generated code directories (Cosmos SDK specific)
                'api',  # Often contains generated protobuf code
            ]


class GitHubSensor:
    """Sensor for GitHub repository documentation"""
    
    def __init__(self, config: GitHubConfig, logger: Optional[logging.Logger] = None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.temp_dir = Path(tempfile.mkdtemp(prefix="github_sensor_"))
        self.logger.info(f"Using temp directory: {self.temp_dir}")

        # Initialize KOI node
        self.koi_node = KOIPartialNode(
            node_name="github-sensor",
            coordinator_url=config.coordinator_url,
            poll_interval=300  # 5 minutes - reduced from 30s to minimize heartbeat events
        )

        # Persistent state for content hash tracking
        self.state = PersistentSensorState('github', Path(__file__).parent)

        # Track processed documents
        self.processed_rids = set()
    
    async def collect_all_repos(self) -> List[Dict[str, Any]]:
        """
        Collect documents from all configured repositories

        Returns:
            List of collected documents
        """
        # Clear processed RIDs for this collection cycle
        # This allows us to track updates to files, not just new files
        self.processed_rids.clear()
        self.logger.info("Starting new collection cycle, cleared processed RIDs")

        all_documents = []
        
        for repo_config in self.config.repos:
            try:
                self.logger.info(f"Collecting from {repo_config['name']}")
                repo_docs = await self.collect_repo(repo_config)
                all_documents.extend(repo_docs)
                self.logger.info(f"Collected {len(repo_docs)} documents from {repo_config['name']}")
            except Exception as e:
                self.logger.error(f"Error collecting repo {repo_config['name']}: {e}")
                continue
        
        self.logger.info(f"Total collected: {len(all_documents)} documents from {len(self.config.repos)} repositories")
        return all_documents
    
    async def collect_repo(self, repo_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Collect documents from a single repository
        
        Args:
            repo_config: Repository configuration
            
        Returns:
            List of documents from the repository
        """
        repo_name = repo_config['name']
        repo_url = repo_config['url']
        branch = repo_config.get('branch', 'main')
        paths = repo_config.get('paths', ['.'])
        
        # Clone repository
        repo_path = self.temp_dir / repo_name
        if repo_path.exists():
            self.logger.info(f"Removing existing repo at {repo_path}")
            shutil.rmtree(repo_path)

        try:
            # Try cloning with specified branch (full history for commit dates)
            self.logger.info(f"Cloning {repo_url} to {repo_path} (branch: {branch})")
            result = subprocess.run(
                ['git', 'clone', '--branch', branch, repo_url, str(repo_path)],
                capture_output=True,
                text=True,
                timeout=120  # Increased timeout for full clone
            )
            self.logger.info(f"Clone result: returncode={result.returncode}")
            
            if result.returncode != 0:
                # Try with master branch if main fails
                if branch == 'main':
                    self.logger.debug("Retrying with master branch")
                    result = subprocess.run(
                        ['git', 'clone', '--depth', '1', '--branch', 'master', repo_url, str(repo_path)],
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    if result.returncode == 0:
                        branch = 'master'
                
                if result.returncode != 0:
                    self.logger.error(f"Failed to clone {repo_url}: {result.stderr}")
                    return []
        
        except subprocess.TimeoutExpired:
            self.logger.error(f"Timeout cloning {repo_url}")
            return []
        except Exception as e:
            self.logger.error(f"Error cloning {repo_url}: {e}")
            return []
        
        documents = []

        # Process specified paths
        for path_pattern in paths:
            files = self.find_files(repo_path, path_pattern)
            self.logger.info(f"Found {len(files)} files matching pattern '{path_pattern}' in {repo_name}")
            # Log a quick breakdown to spot extension drop-offs (e.g., proto)
            if files:
                from collections import Counter
                ext_counts = Counter(f.suffix or "no_extension" for f in files)
                self.logger.info(f"Extension breakdown for '{repo_name}/{path_pattern}': {dict(ext_counts)}")

            for file_path in files:
                doc = self.process_file(file_path, repo_name, repo_url, branch, repo_path)
                if doc:
                    documents.append(doc)
                else:
                    self.logger.debug(f"No document created for {file_path}")
        
        # Clean up cloned repo
        try:
            shutil.rmtree(repo_path)
        except Exception as e:
            self.logger.warning(f"Failed to clean up {repo_path}: {e}")
        
        return documents
    
    def find_files(self, repo_path: Path, pattern: str) -> List[Path]:
        """
        Find files matching pattern in repository
        
        Args:
            repo_path: Path to repository
            pattern: File pattern (glob or path)
            
        Returns:
            List of matching file paths
        """
        files = []
        
        # Handle different pattern types
        if pattern == '.':
            # All files recursively (documentation + code)
            for ext in self.config.file_extensions:
                files.extend(repo_path.glob(f'**/{ext}'))
        elif '*' in pattern:
            # Glob pattern
            files.extend(repo_path.glob(pattern))
        else:
            # Specific directory or file
            target = repo_path / pattern
            if target.is_dir():
                # Search for all file types in directory
                for ext in self.config.file_extensions:
                    files.extend(target.glob(f'**/{ext}'))
            elif target.exists():
                files.append(target)
        
        # Filter out excluded directories and binary files
        filtered_files = []
        excluded_extensions = [
            '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico',
            '.pdf', '.zip', '.tar', '.gz', '.bz2', '.exe',
            '.dll', '.so', '.dylib', '.woff', '.ttf', '.eot'
        ]
        
        for f in files:
            # Skip excluded directories
            parts = f.parts
            if any(p.startswith('.') or p in self.config.excluded_dirs for p in parts):
                continue
            
            # Skip binary files
            if f.suffix.lower() in excluded_extensions:
                continue
            
            # Skip test fixtures and mocks
            if 'fixtures' in str(f) or 'mocks' in str(f) or '__mocks__' in str(f):
                continue
            
            filtered_files.append(f)

        self.logger.info(f"Filtering stats for pattern '{pattern}': {len(files)} -> {len(filtered_files)} after exclusions")
        
        return filtered_files
    
    def process_file(self, file_path: Path, repo_name: str, repo_url: str, branch: str, repo_path: Path) -> Optional[Dict[str, Any]]:
        """
        Process a single file into a document

        Args:
            file_path: Path to file
            repo_name: Repository name
            repo_url: Repository URL
            branch: Git branch
            repo_path: Path to cloned repository root

        Returns:
            Document dictionary or None if processing fails
        """
        try:
            # Read file content
            try:
                content = file_path.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                # Try with latin-1 encoding
                try:
                    content = file_path.read_text(encoding='latin-1')
                except:
                    self.logger.warning(f"Could not decode {file_path}")
                    return None
            
            # Skip empty files
            if not content.strip():
                return None

            # Check file size - skip very large files (likely generated)
            MAX_FILE_SIZE = 500_000  # 500KB
            if len(content.encode('utf-8')) > MAX_FILE_SIZE:
                self.logger.debug(f"Skipping large file {file_path}: {len(content.encode('utf-8'))} bytes")
                return None

            # Generate document metadata
            # Get path relative to the repo root (not temp dir)
            relative_path = file_path.relative_to(repo_path)
            file_url = f"{repo_url}/blob/{branch}/{relative_path}"

            # Generate RID (no colons allowed in RID system)
            rid = f"github_{repo_name}_{relative_path}"
            rid = rid.replace('/', '_').replace(' ', '_').replace(':', '_')
            
            # Track this RID within this collection cycle to avoid duplicates
            if rid in self.processed_rids:
                # Already processed in this collection cycle
                return None
            self.processed_rids.add(rid)
            
            # Extract publication date
            published_at = None
            confidence = 0.0
            
            # For markdown files, try to extract date from content
            if file_path.suffix in ['.md', '.mdx']:
                import re
                # Look for date in frontmatter
                date_pattern = r'date:\s*["\']*(\d{4}-\d{2}-\d{2})'
                match = re.search(date_pattern, content[:500])  # Check first 500 chars
                if match:
                    try:
                        published_at = datetime.strptime(match.group(1), '%Y-%m-%d')
                        confidence = 0.8
                    except:
                        pass
            
            # Use git log to get last commit info for this file
            commit_message = None
            commit_author = None
            commit_sha = None
            commit_date_str = None
            if not published_at:
                try:
                    # Get the last commit info for this file
                    # Format: commit hash|commit date|author|subject|body
                    import subprocess
                    result = subprocess.run(
                        ['git', 'log', '-1', '--format=%H|%cI|%an|%s|%b', str(file_path)],
                        cwd=repo_path,  # repo root
                        capture_output=True,
                        text=True
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        parts = result.stdout.strip().split('|', 4)
                        if len(parts) >= 1:
                            commit_sha = parts[0]
                        if len(parts) >= 2:
                            commit_date_str = parts[1]
                            published_at = datetime.fromisoformat(commit_date_str.replace('Z', '+00:00'))
                            confidence = 1.0  # Git commit dates are 100% verifiable
                        if len(parts) >= 3:
                            commit_author = parts[2]
                        if len(parts) >= 4:
                            # Combine subject and body
                            commit_message = parts[3]
                            if len(parts) >= 5 and parts[4].strip():
                                commit_message += "\n" + parts[4]
                except Exception as e:
                    self.logger.debug(f"Could not get git info for {file_path}: {e}")

            # Final fallback to file modification time
            if not published_at:
                try:
                    import os
                    stat = os.stat(file_path)
                    published_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                    confidence = 0.6  # Lower confidence for file system dates
                except:
                    pass

            
            # Create document title from repo and file path
            title = f"{repo_name}: {str(relative_path)}"

            if file_path.suffix == '.proto':
                self.logger.info(f"Processing proto file: {relative_path}")

            # Create document compatible with document_to_bundle
            doc = {
                "id": rid,  # Used by document_to_rid as fallback
                "title": title,  # Required by document_to_bundle
                "source": "github",
                "source_type": "github",  # Used by document_to_rid
                "url": file_url,  # Important for attribution
                "content": content,
                "author": commit_author,  # From git log
                "tags": [repo_name, branch, file_path.suffix or "no_extension"],
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "last_modified": published_at.isoformat() if published_at else None,
                "metadata": {
                    # Publication date metadata for Daily Curator
                    "published_at": published_at.isoformat() if published_at else None,
                    "published_confidence": confidence,

                    # Git commit metadata for context
                    "commit_message": commit_message,
                    "commit_author": commit_author,
                    "commit_sha": commit_sha,
                    "commit_date": commit_date_str,

                    # GitHub specific metadata
                    "repo": repo_name,
                    "branch": branch,
                    # Full file path format for Code Graph Processor: org/repo/path/to/file
                    "file_path": f"regen-network/{repo_name}/{relative_path}",

                    # File metadata
                    "file_type": file_path.suffix or "no_extension",
                    "file_size": len(content),
                    "lines": content.count('\n') + 1
                }
            }
            
            return doc
            
        except Exception as e:
            self.logger.error(f"Error processing {file_path}: {e}")
            return None
    
    async def send_heartbeat_event(self, response_to: Optional[str] = None):
        """Send a heartbeat event to register with coordinator

        Args:
            response_to: Optional RID to respond to for ping requests
        """
        try:
            # Create a heartbeat bundle
            heartbeat_data = {
                "type": "sensor_heartbeat",
                "sensor_id": "github-sensor",
                "sensor_type": "github",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "active",
                "monitoring": [repo['name'] for repo in self.config.repos]
            }

            # Add response_to if this is a ping response
            if response_to:
                heartbeat_data["response_to"] = response_to

            # Create document for heartbeat with required fields
            heartbeat_document = {
                'id': f"github_heartbeat_{int(datetime.now().timestamp())}",
                'title': 'GitHub Sensor Heartbeat',
                'url': '',
                'type': 'heartbeat',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'content': json.dumps(heartbeat_data),
                'metadata': {
                    'sensor_type': 'github',
                    'sensor_id': 'github-sensor',
                    'event_type': 'HEARTBEAT'
                }
            }

            # Convert to bundle and emit
            bundle = document_to_bundle(heartbeat_document)
            await self.koi_node.emit_new_event(bundle)

            if response_to:
                self.logger.info(f"Sent ping response heartbeat to coordinator (responding to {response_to})")
            else:
                self.logger.info("Sent heartbeat event to register with coordinator")

        except Exception as e:
            self.logger.error(f"Error sending heartbeat: {e}")

    async def send_periodic_heartbeats(self):
        """Send periodic heartbeats every 30 minutes"""
        while True:
            try:
                await asyncio.sleep(1800)  # 30 minutes
                await self.send_heartbeat_event()
                self.logger.info("Sent periodic heartbeat")
            except asyncio.CancelledError:
                self.logger.info("Periodic heartbeat task cancelled")
                break
            except Exception as e:
                self.logger.error(f"Error in periodic heartbeat: {e}")

    async def handle_coordinator_events(self):
        """Listen for and handle coordinator events like ping requests"""
        while True:
            try:
                # KOIPartialNode doesn't have poll_coordinator_events, skip for now
                await asyncio.sleep(30)
                continue

                # Check for coordinator events
                # events = await self.koi_node.poll_coordinator_events()

                # for event in events:
                #     event_type = event.get('event_type')

                #     if event_type == 'PING_REQUEST':
                #         # Check if ping is for this sensor
                #         target_sensor = event.get('target_sensor')
                #         if target_sensor == 'github-sensor' or target_sensor == 'github':
                #             self.logger.info(f"Received ping request: {event.get('rid')}")
                #             # Respond with heartbeat
                #             await self.send_heartbeat_event(response_to=event.get('rid'))

                # await asyncio.sleep(30)  # Check every 30 seconds

            except asyncio.CancelledError:
                self.logger.info("Coordinator event handler cancelled")
                break
            except Exception as e:
                self.logger.error(f"Error handling coordinator events: {e}")
                await asyncio.sleep(30)

    async def send_to_koi(self, documents: List[Dict[str, Any]]) -> int:
        """Send documents to KOI coordinator as events"""
        success_count = 0

        # Ensure KOI node session is active
        if not self.koi_node.session or self.koi_node.session.closed:
            self.logger.warning("KOI node session not active, reinitializing...")
            import aiohttp
            if self.koi_node.session and not self.koi_node.session.closed:
                await self.koi_node.session.close()
            self.koi_node.session = aiohttp.ClientSession()
            self.logger.info("KOI node session reinitialized")

        for doc in documents:
            try:
                # Create bundle from document
                bundle = document_to_bundle(doc, source_node="github-sensor")

                # Calculate content hash
                content = doc.get('content', '')
                content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
                rid = doc.get('id', doc.get('rid', 'unknown'))

                # Check if content changed
                previous_hash = self.state.metadata.get(f"hash_{rid}")

                if previous_hash and previous_hash != content_hash:
                    # Content changed - emit UPDATE
                    await self.koi_node.emit_update_event(bundle)
                    self.logger.info(f"UPDATE: {rid}")
                elif not previous_hash:
                    # New content - emit NEW
                    await self.koi_node.emit_new_event(bundle)
                    self.logger.info(f"NEW: {rid}")
                else:
                    # No change - skip
                    self.logger.debug(f"SKIP (no change): {rid}")
                    continue

                # Store hash
                self.state.metadata[f"hash_{rid}"] = content_hash
                success_count += 1

            except Exception as e:
                self.logger.error(f"Error sending document {doc.get('id', doc.get('rid', 'unknown'))}: {e}")
                continue

        return success_count
    
    async def start(self):
        """Start the GitHub sensor"""
        self.logger.info("Starting GitHub KOI Sensor")

        # Start KOI node
        await self.koi_node.start()

        # Send startup heartbeat to register with coordinator
        await self.send_heartbeat_event()

        # Start background tasks for periodic heartbeats and coordinator event handling
        heartbeat_task = asyncio.create_task(self.send_periodic_heartbeats())
        coordinator_task = asyncio.create_task(self.handle_coordinator_events())

        # Initial collection
        documents = await self.collect_all_repos()
        if documents:
            sent_count = await self.send_to_koi(documents)
            self.logger.info(f"Initial collection: sent {sent_count}/{len(documents)} documents to KOI")
        # Save state after collection cycle
        self.state.save()
        self.logger.info(f"Saved state with {len(self.state.metadata)} hash entries")

        # Start monitoring loop
        while True:
            await asyncio.sleep(3600)  # Check every hour
            documents = await self.collect_all_repos()
            if documents:
                sent_count = await self.send_to_koi(documents)
                self.logger.info(f"Periodic collection: sent {sent_count}/{len(documents)} documents to KOI")
            # Save state after collection cycle
            self.state.save()
            self.logger.info(f"Saved state with {len(self.state.metadata)} hash entries")

    def cleanup(self):
        """Clean up temporary directory"""
        try:
            if self.temp_dir.exists():
                shutil.rmtree(self.temp_dir)
                self.logger.info(f"Cleaned up temp directory: {self.temp_dir}")
        except Exception as e:
            self.logger.warning(f"Failed to clean up temp directory: {e}")

    async def stop(self):
        """Stop the GitHub sensor and cleanup"""
        self.logger.info("Stopping GitHub KOI Sensor")

        # Stop KOI node
        await self.koi_node.stop()

        # Cleanup temp directory
        self.cleanup()


async def main():
    """Test the GitHub sensor"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)
    
    # Configure repositories
    config = GitHubConfig(
        repos=[
            # Regen Network Org
            {
                "name": "regen-ledger",
                "url": "https://github.com/regen-network/regen-ledger",
                "branch": "main",
                "paths": ["."]
            },
            {
                "name": "regen-web",
                "url": "https://github.com/regen-network/regen-web",
                "branch": "master",
                "paths": ["."]  # Changed from ["docs", "README.md"] to scan entire codebase
            },
            {
                "name": "regen-data-standards",
                "url": "https://github.com/regen-network/regen-data-standards",
                "branch": "main",
                "paths": ["."]
            },
            {
                "name": "regen-registry-handbook",
                "url": "https://github.com/regen-network/regen-registry-handbook",
                "branch": "main",
                "paths": ["."]
            },
            {
                "name": "regen-registry-methodology-library",
                "url": "https://github.com/regen-network/regen-registry-methodology-library",
                "branch": "main",
                "paths": ["."]  # Changed from ["docs", "README.md", "src"] for complete coverage
            },
            # GAIA AI Agent Org - KOI Protocol repositories
            {
                "name": "koi-sensors",
                "url": "https://github.com/gaiaaiagent/koi-sensors",
                "branch": "main",
                "paths": ["."]
            },
            {
                "name": "koi-processor",
                "url": "https://github.com/gaiaaiagent/koi-processor",
                "branch": "main",
                "paths": ["."]
            },
            {
                "name": "koi-research",
                "url": "https://github.com/gaiaaiagent/koi-research",
                "branch": "main",
                "paths": ["."]
            },
            {
                "name": "regen-koi-mcp",
                "url": "https://github.com/gaiaaiagent/regen-koi-mcp",
                "branch": "main",
                "paths": ["."]
            },
            {
                "name": "regen-python-mcp",
                "url": "https://github.com/gaiaaiagent/regen-python-mcp",
                "branch": "main",
                "paths": ["."]
            },
            # Batch 1 - High priority new repos
            {
                "name": "regen-compute",
                "url": "https://github.com/regen-network/regen-compute",
                "branch": "main",
                "paths": ["."]
            },
            {
                "name": "revenue-hunter-cec",
                "url": "https://github.com/regen-network/revenue-hunter-cec",
                "branch": "main",
                "paths": ["."]
            },
            {
                "name": "regen-ai-core",
                "url": "https://github.com/regen-network/regen-ai-core",
                "branch": "main",
                "paths": ["."]
            },
            {
                "name": "regen-ai-claude",
                "url": "https://github.com/gaiaaiagent/regen-ai-claude",
                "branch": "main",
                "paths": ["."]
            },
            # Batch 2 - Additional repos
            {
                "name": "regen-js",
                "url": "https://github.com/regen-network/regen-js",
                "branch": "main",
                "paths": ["."]
            },
            {
                "name": "agentic-tokenomics",
                "url": "https://github.com/regen-network/agentic-tokenomics",
                "branch": "main",
                "paths": ["."]
            },
            {
                "name": "protocol-politicians",
                "url": "https://github.com/regen-network/protocol-politicians",
                "branch": "main",
                "paths": ["."]
            },
            {
                "name": "regen-claude-config",
                "url": "https://github.com/regen-network/regen-claude-config",
                "branch": "main",
                "paths": ["."]
            },
            {
                "name": "regenie-corpus",
                "url": "https://github.com/regen-network/regenie-corpus",
                "branch": "main",
                "paths": ["."]
            },
            {
                "name": "mcp",
                "url": "https://github.com/regen-network/mcp",
                "branch": "main",
                "paths": ["."]
            },
            {
                "name": "pacto-framework",
                "url": "https://github.com/regen-network/pacto-framework",
                "branch": "main",
                "paths": ["."]
            },
            {
                "name": "koi-gov",
                "url": "https://github.com/regen-network/koi-gov",
                "branch": "main",
                "paths": ["."]
            },
        ]
    )
    
    sensor = GitHubSensor(config, logger)

    try:
        await sensor.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        await sensor.stop()


if __name__ == "__main__":
    asyncio.run(main())
