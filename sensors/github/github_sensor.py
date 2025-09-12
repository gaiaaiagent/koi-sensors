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
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import hashlib
import subprocess
import base64

@dataclass
class GitHubConfig:
    """GitHub sensor configuration"""
    repos: List[Dict[str, Any]]
    koi_bridge_url: str = "http://localhost:8005/api/event"
    source_sensor: str = "github-sensor"
    
    # File patterns to index
    doc_extensions: List[str] = None
    
    # Directories to exclude
    excluded_dirs: List[str] = None
    
    def __post_init__(self):
        if self.doc_extensions is None:
            self.doc_extensions = [
                '*.md', '*.MD', '*.mdx',  # Markdown
                '*.rst', '*.txt', '*.asciidoc',  # Other docs
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


class GitHubSensor:
    """Sensor for GitHub repository documentation"""
    
    def __init__(self, config: GitHubConfig, logger: Optional[logging.Logger] = None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.temp_dir = Path(tempfile.mkdtemp(prefix="github_sensor_"))
        self.logger.info(f"Using temp directory: {self.temp_dir}")
        
        # Track processed documents
        self.processed_rids = set()
    
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
        
        # Clone repository
        repo_path = self.temp_dir / repo_name
        if repo_path.exists():
            shutil.rmtree(repo_path)
        
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
        
        documents = []
        
        # Process specified paths
        for path_pattern in paths:
            files = self.find_files(repo_path, path_pattern)
            
            for file_path in files:
                doc = self.process_file(file_path, repo_name, repo_url, branch)
                if doc:
                    documents.append(doc)
        
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
        
        return filtered_files
    
    def process_file(self, file_path: Path, repo_name: str, repo_url: str, branch: str) -> Optional[Dict[str, Any]]:
        """
        Process a single file into a document
        
        Args:
            file_path: Path to file
            repo_name: Repository name
            repo_url: Repository URL
            branch: Git branch
            
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
            
            # Generate document metadata
            relative_path = file_path.relative_to(file_path.parent.parent.parent)
            file_url = f"{repo_url}/blob/{branch}/{relative_path}"
            
            # Generate RID
            rid = f"github:{repo_name}:{relative_path}"
            rid = rid.replace('/', ':').replace(' ', '_')
            
            # Skip if already processed
            if rid in self.processed_rids:
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
            
            # Fallback to git commit date (would need git integration)
            if not published_at:
                # For now, use file modification time as approximation
                try:
                    import os
                    stat = os.stat(file_path)
                    published_at = datetime.fromtimestamp(stat.st_mtime)
                    confidence = 0.6  # Lower confidence for file system dates
                except:
                    pass
            
            # Create document
            doc = {
                "rid": rid,
                "source": "github",
                "repo": repo_name,
                "file_path": str(relative_path),
                "url": file_url,
                "branch": branch,
                "content": content,
                "metadata": {
                    # Publication date metadata for Daily Curator
                    "published_at": published_at.isoformat() if published_at else None,
                    "published_confidence": confidence,
                    
                    # Original metadata
                    "file_type": file_path.suffix or "no_extension",
                    "file_size": len(content),
                    "lines": content.count('\n') + 1,
                    "collected_at": datetime.now(timezone.utc).isoformat()
                }
            }
            
            return doc
            
        except Exception as e:
            self.logger.error(f"Error processing {file_path}: {e}")
            return None
    
    async def send_to_koi(self, documents: List[Dict[str, Any]]) -> int:
        """
        Send documents to KOI Event Bridge
        
        Args:
            documents: List of documents to send
            
        Returns:
            Number of successfully sent documents
        """
        success_count = 0
        
        for doc in documents:
            try:
                # Generate CID from content
                content_str = json.dumps(doc, sort_keys=True)
                cid = hashlib.sha256(content_str.encode()).hexdigest()
                
                # Create bundle
                bundle = {
                    "rid": doc["rid"],
                    "cid": cid,
                    "content": doc,
                    "metadata": doc.get("metadata", {}),
                    "manifest": {
                        "version": "1.0.0",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "source": self.config.source_sensor
                    }
                }
                
                # Create event
                event = {
                    "event_type": "NEW",
                    "source_sensor": self.config.source_sensor,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "bundle": bundle
                }
                
                # Send to KOI Event Bridge
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        f"{self.config.koi_bridge_url}/process",
                        json=event
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        self.logger.info(
                            f"Sent document {doc['rid']}: "
                            f"{result.get('chunks_created')} chunks, "
                            f"{result.get('embeddings_created')} embeddings"
                        )
                        success_count += 1
                    else:
                        self.logger.error(f"Failed to send {doc['rid']}: {response.status_code}")
                        
            except Exception as e:
                self.logger.error(f"Error sending document {doc.get('rid', 'unknown')}: {e}")
                continue
        
        return success_count
    
    def cleanup(self):
        """Clean up temporary directory"""
        try:
            if self.temp_dir.exists():
                shutil.rmtree(self.temp_dir)
                self.logger.info(f"Cleaned up temp directory: {self.temp_dir}")
        except Exception as e:
            self.logger.warning(f"Failed to clean up temp directory: {e}")


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
            {
                "name": "regen-ledger",
                "url": "https://github.com/regen-network/regen-ledger",
                "branch": "main",
                "paths": ["."]
            },
            {
                "name": "regen-web",
                "url": "https://github.com/regen-network/regen-web",
                "branch": "main",
                "paths": ["docs", "README.md"]
            },
            {
                "name": "regen-data-standards",
                "url": "https://github.com/regen-network/regen-data-standards",
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
                "paths": ["docs", "README.md", "src"]
            }
        ]
    )
    
    sensor = GitHubSensor(config, logger)
    
    try:
        # Collect documents
        logger.info("Starting GitHub repository collection...")
        documents = await sensor.collect_all_repos()
        
        # Save to file for inspection
        output_dir = Path("test_outputs")
        output_dir.mkdir(exist_ok=True)
        
        output_file = output_dir / f"github_docs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, 'w') as f:
            json.dump(documents, f, indent=2)
        
        logger.info(f"Saved {len(documents)} documents to {output_file}")
        
        # Send to KOI if bridge is running
        try:
            success_count = await sensor.send_to_koi(documents)
            logger.info(f"Successfully sent {success_count}/{len(documents)} documents to KOI")
        except Exception as e:
            logger.warning(f"Could not send to KOI (bridge may not be running): {e}")
        
    finally:
        sensor.cleanup()


if __name__ == "__main__":
    asyncio.run(main())