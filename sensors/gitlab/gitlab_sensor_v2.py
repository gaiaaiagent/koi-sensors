"""
KOI GitLab Sensor - Repository documentation collector using KOI Protocol
Indexes documentation from GitLab repositories (specifically Regen whitepapers)
"""

import asyncio
import hashlib
import json
import logging
import tempfile
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import subprocess
import sys

# Add parent directories to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.rid_system import RID
from koi_protocol.core.bundle_system import Bundle, document_to_bundle


@dataclass
class GitLabConfig:
    """GitLab sensor configuration"""
    repos: List[Dict[str, Any]]
    coordinator_url: str = "http://localhost:8005"
    source_sensor: str = "gitlab-sensor"

    # File patterns to index
    doc_extensions: List[str] = None

    # Directories to exclude
    excluded_dirs: List[str] = None

    def __post_init__(self):
        if self.doc_extensions is None:
            self.doc_extensions = [
                '*.md', '*.MD', '*.mdx',  # Markdown
                '*.rst', '*.txt', '*.asciidoc',  # Other docs
                '*.pdf', '*.tex',  # Whitepapers
                '*.json', '*.yaml', '*.yml',  # Config/API specs
                '*.toml', '*.ini', '*.cfg',  # Config files
                'LICENSE*', 'COPYRIGHT*', 'NOTICE*',  # Legal docs
                'README*', 'CHANGELOG*', 'CONTRIBUTING*'  # Common docs
            ]

        if self.excluded_dirs is None:
            self.excluded_dirs = [
                'node_modules', 'vendor', 'dist', 'build', '.git',
                '__pycache__', '.pytest_cache', 'coverage', '.next',
                'out', 'target', 'bin', '.vscode', '.idea'
            ]


class GitLabDocumentRID(RID):
    """GitLab document resource identifier: orn:gitlab.{repo}.{file_path}"""

    def __init__(self, repo_name: str, file_path: str):
        # Create a clean identifier
        clean_repo = repo_name.replace('/', '_').replace('-', '_')
        clean_path = file_path.replace('/', '_').replace('.', '_').replace('-', '_')
        doc_id = f"{clean_repo}.{clean_path}"
        super().__init__("orn", f"gitlab.{doc_id}")


class GitLabSensor:
    """Sensor for GitLab repository documentation using KOI Protocol"""

    def __init__(self, config: GitLabConfig, logger: Optional[logging.Logger] = None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.temp_dir = Path(tempfile.mkdtemp(prefix="gitlab_sensor_"))
        self.logger.info(f"Using temp directory: {self.temp_dir}")

        # Initialize KOI node
        self.koi_node = KOIPartialNode(
            node_name="gitlab-sensor",
            coordinator_url=config.coordinator_url,
            poll_interval=30
        )

        # Track processed documents
        self.processed_rids = set()
        self.repo_states = {}  # Track repo commit hashes

    async def start(self):
        """Start the GitLab sensor"""
        self.logger.info("Starting GitLab KOI Sensor")

        # Start KOI node
        await self.koi_node.start()

        # Initial collection
        await self.collect_all_repos()

        # Start monitoring loop
        while True:
            await asyncio.sleep(3600)  # Check every hour
            await self.collect_all_repos()

    async def collect_all_repos(self) -> List[Dict[str, Any]]:
        """
        Collect documents from all configured repositories

        Returns:
            List of collected documents
        """
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

        # Check if repo already cloned
        repo_path = self.temp_dir / repo_name

        if repo_path.exists():
            # Pull updates
            try:
                self.logger.debug(f"Pulling updates for {repo_name}")
                result = subprocess.run(
                    ['git', 'pull'],
                    cwd=str(repo_path),
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                if result.returncode != 0:
                    self.logger.warning(f"Failed to pull updates for {repo_name}: {result.stderr}")
                    # Re-clone if pull fails
                    shutil.rmtree(repo_path)
            except Exception as e:
                self.logger.warning(f"Error pulling updates for {repo_name}: {e}")
                shutil.rmtree(repo_path)

        # Clone if not exists
        if not repo_path.exists():
            try:
                # Try cloning with specified branch
                self.logger.debug(f"Cloning {repo_url} to {repo_path} (branch: {branch})")
                result = subprocess.run(
                    ['git', 'clone', '--depth', '1', '--branch', branch, repo_url, str(repo_path)],
                    capture_output=True,
                    text=True,
                    timeout=60
                )

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

        # Get current commit hash
        try:
            result = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                cwd=str(repo_path),
                capture_output=True,
                text=True
            )
            current_commit = result.stdout.strip() if result.returncode == 0 else None

            # Check if repo has new commits
            previous_commit = self.repo_states.get(repo_name)
            is_new = previous_commit != current_commit

            if current_commit:
                self.repo_states[repo_name] = current_commit
        except Exception as e:
            self.logger.warning(f"Could not get commit hash for {repo_name}: {e}")
            is_new = True

        documents = []
        whitepapers = []

        # Process specified paths
        for path_pattern in paths:
            files = self.find_files(repo_path, path_pattern)

            for file_path in files:
                # Track whitepapers specially
                if file_path.suffix.lower() in ['.pdf', '.tex'] and 'whitepaper' in file_path.name.lower():
                    whitepapers.append(file_path)

                doc = await self.process_file(file_path, repo_name, repo_url, branch, is_new)
                if doc:
                    documents.append(doc)

        # Log found whitepapers
        if whitepapers:
            self.logger.info(f"Found {len(whitepapers)} whitepapers:")
            for wp in whitepapers:
                self.logger.info(f"  - {repo_name}/{wp.relative_to(repo_path)}")

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
            # All documentation files recursively
            for ext in self.config.doc_extensions:
                files.extend(repo_path.glob(f'**/{ext}'))
        elif '*' in pattern:
            # Glob pattern
            files.extend(repo_path.glob(pattern))
        else:
            # Specific directory or file
            target = repo_path / pattern
            if target.is_dir():
                # Search for all doc types in directory
                for ext in self.config.doc_extensions:
                    files.extend(target.glob(f'**/{ext}'))
            elif target.exists():
                files.append(target)

        # Filter out excluded directories but keep PDFs and TEX files
        filtered_files = []
        binary_extensions = [
            '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico',
            '.zip', '.tar', '.gz', '.bz2', '.exe',
            '.dll', '.so', '.dylib', '.woff', '.ttf', '.eot'
        ]

        for f in files:
            # Check if in excluded directory
            if any(excluded in f.parts for excluded in self.config.excluded_dirs):
                continue

            # Allow PDF and TEX files (for whitepapers), skip other binaries
            if f.suffix.lower() in binary_extensions:
                continue

            # Check if it's actually a file
            if not f.is_file():
                continue

            filtered_files.append(f)

        return filtered_files

    async def process_file(self, file_path: Path, repo_name: str, repo_url: str,
                          branch: str, is_new_commit: bool) -> Optional[Dict[str, Any]]:
        """
        Process a single file and emit KOI event

        Args:
            file_path: Path to file
            repo_name: Repository name
            repo_url: Repository URL
            branch: Git branch
            is_new_commit: Whether this is from a new commit

        Returns:
            Document data if processed successfully
        """
        try:
            # Handle different file types
            content = ""
            is_binary = file_path.suffix.lower() in ['.pdf']

            if is_binary:
                # For PDFs, just note that it exists
                content = f"[Binary file: {file_path.name}]\nFile type: {file_path.suffix}\nSize: {file_path.stat().st_size} bytes"
            else:
                # Read text content
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                except UnicodeDecodeError:
                    # Try with different encoding
                    try:
                        with open(file_path, 'r', encoding='latin-1') as f:
                            content = f.read()
                    except:
                        # Mark as binary if can't read
                        content = f"[Unable to read file: {file_path.name}]"
                        is_binary = True

            # Skip empty files (unless binary)
            if not content.strip() and not is_binary:
                return None

            # Get relative path
            repo_path = self.temp_dir / repo_name
            relative_path = file_path.relative_to(repo_path)

            # Construct GitLab URL
            file_url = f"{repo_url}/-/blob/{branch}/{relative_path}"

            # Generate RID
            rid = GitLabDocumentRID(repo_name, str(relative_path))

            # Skip if already processed (unless new commit)
            rid_str = rid.to_string()
            if rid_str in self.processed_rids and not is_new_commit:
                return None
            self.processed_rids.add(rid_str)

            # Extract metadata
            file_stat = file_path.stat()
            modified_time = datetime.fromtimestamp(file_stat.st_mtime, timezone.utc)

            # Determine document type
            doc_type = "whitepaper" if "whitepaper" in file_path.name.lower() else "documentation"

            # Create document in KOI format
            document = {
                "id": f"gitlab_{repo_name}_{hashlib.sha256(str(relative_path).encode()).hexdigest()[:8]}",
                "source": f"gitlab:{repo_name}",
                "source_type": "repository",
                "url": file_url,
                "title": f"{repo_name}/{relative_path}",
                "content": content,
                "metadata": {
                    "repository": repo_name,
                    "branch": branch,
                    "file_path": str(relative_path),
                    "file_type": file_path.suffix or "no_extension",
                    "file_size": file_stat.st_size if is_binary else len(content),
                    "lines": 0 if is_binary else content.count('\n') + 1,
                    "last_modified": modified_time.isoformat(),
                    "commit_hash": self.repo_states.get(repo_name, ""),
                    "document_type": doc_type,
                    "is_binary": is_binary,
                    "collection_method": "gitlab_sensor",
                    "koi_sensor": "gitlab-sensor"
                },
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "last_modified": modified_time.isoformat(),
                "tags": self.generate_tags(repo_name, str(relative_path), content, doc_type)
            }

            # Create KOI Bundle
            bundle = document_to_bundle(document, self.koi_node.node_id)

            # Emit KOI event
            event_type = "NEW" if is_new_commit else "UPDATE"
            if event_type == "NEW":
                await self.koi_node.emit_new_event(bundle)
            else:
                await self.koi_node.emit_update_event(bundle)

            self.logger.info(f"Emitted {event_type} event for {repo_name}/{relative_path} (RID: {rid_str})")

            return document

        except Exception as e:
            self.logger.error(f"Error processing {file_path}: {e}")
            return None

    def generate_tags(self, repo_name: str, file_path: str, content: str, doc_type: str) -> List[str]:
        """Generate tags based on repository, file path, content, and document type"""
        tags = []

        # Add repository as tag
        tags.append(f"repo:{repo_name}")

        # Add document type
        tags.append(doc_type)

        # Add file type tags
        if 'README' in file_path.upper():
            tags.append("readme")
        if 'LICENSE' in file_path.upper():
            tags.append("license")
        if 'WHITEPAPER' in file_path.upper():
            tags.append("whitepaper")
        if 'PROTOCOL' in file_path.upper():
            tags.append("protocol")
        if 'ARCHITECTURE' in file_path.upper():
            tags.append("architecture")

        # Add technology tags based on file extensions
        if file_path.endswith('.md') or file_path.endswith('.mdx'):
            tags.append("markdown")
        if file_path.endswith('.pdf'):
            tags.append("pdf")
        if file_path.endswith('.tex'):
            tags.append("latex")
        if file_path.endswith('.yaml') or file_path.endswith('.yml'):
            tags.append("yaml")
        if file_path.endswith('.json'):
            tags.append("json")

        # Content-based tags (only for non-binary)
        if not any(ext in file_path.lower() for ext in ['.pdf']):
            content_lower = content.lower()
            if 'cosmos' in content_lower:
                tags.append("cosmos")
            if 'blockchain' in content_lower:
                tags.append("blockchain")
            if 'ecocredit' in content_lower:
                tags.append("ecocredit")
            if 'governance' in content_lower:
                tags.append("governance")
            if 'protocol' in content_lower:
                tags.append("protocol")
            if 'architecture' in content_lower:
                tags.append("architecture")

        return list(set(tags))  # Remove duplicates

    async def stop(self):
        """Stop the GitLab sensor and cleanup"""
        self.logger.info("Stopping GitLab KOI Sensor")

        # Stop KOI node
        await self.koi_node.stop()

        # Cleanup temp directory
        try:
            if self.temp_dir.exists():
                shutil.rmtree(self.temp_dir)
                self.logger.info(f"Cleaned up temp directory: {self.temp_dir}")
        except Exception as e:
            self.logger.warning(f"Failed to clean up temp directory: {e}")


async def main():
    """Run the GitLab sensor"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)

    # Configure repositories
    config = GitLabConfig(
        repos=[
            {
                "name": "regen-public-docs",
                "url": "https://gitlab.com/regen-network/regen-public-docs",
                "branch": "main",
                "paths": ["."],
                "notes": "Regen Network whitepapers and protocols"
            }
        ],
        coordinator_url="http://localhost:8005"
    )

    # Create and start sensor
    sensor = GitLabSensor(config, logger)

    try:
        await sensor.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        await sensor.stop()


if __name__ == "__main__":
    asyncio.run(main())