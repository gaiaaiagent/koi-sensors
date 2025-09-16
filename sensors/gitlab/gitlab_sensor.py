"""
KOI GitLab Sensor - Repository documentation collector
Indexes documentation from GitLab repositories (specifically Regen whitepapers)
"""

import asyncio
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


@dataclass
class GitLabConfig:
    """GitLab sensor configuration"""
    repos: List[Dict[str, Any]]
    koi_bridge_url: str = "http://localhost:8200/process-koi-event"
    koi_coordinator_url: str = "http://localhost:8005"
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
                '*.pdf',  # PDFs (whitepapers often in PDF)
                '*.json', '*.yaml', '*.yml',  # Config/API specs
                '*.tex',  # LaTeX source files
                'LICENSE*', 'COPYRIGHT*', 'NOTICE*',  # Legal docs
                'README*', 'WHITEPAPER*'  # Common docs
            ]
        
        if self.excluded_dirs is None:
            self.excluded_dirs = [
                'node_modules', 'vendor', 'dist', 'build', '.git',
                '__pycache__', '.pytest_cache', 'coverage'
            ]


class GitLabSensor:
    """Sensor for GitLab repository documentation"""
    
    def __init__(self, config: GitLabConfig, logger: Optional[logging.Logger] = None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.temp_dir = Path(tempfile.mkdtemp(prefix="gitlab_sensor_"))
        self.logger.info(f"Using temp directory: {self.temp_dir}")

        # Track processed documents
        self.processed_rids = set()
        self.documents_sent = 0
    
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
        branch = repo_config.get('branch', 'master')  # GitLab often uses master
        paths = repo_config.get('paths', ['.'])
        
        # Clone repository
        repo_path = self.temp_dir / repo_name
        if repo_path.exists():
            shutil.rmtree(repo_path)
        
        try:
            # Try cloning with specified branch (full history for git dates)
            self.logger.debug(f"Cloning {repo_url} to {repo_path} (branch: {branch})")
            result = subprocess.run(
                ['git', 'clone', '--branch', branch, repo_url, str(repo_path)],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                # Try with main branch if master fails
                if branch == 'master':
                    self.logger.debug("Retrying with main branch")
                    result = subprocess.run(
                        ['git', 'clone', '--branch', 'main', repo_url, str(repo_path)],
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    if result.returncode == 0:
                        branch = 'main'
                
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
        
        # Filter out excluded directories
        filtered_files = []
        excluded_extensions = [
            '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico',
            '.zip', '.tar', '.gz', '.bz2', '.exe',
            '.dll', '.so', '.dylib', '.woff', '.ttf', '.eot'
        ]
        
        for f in files:
            # Skip excluded directories
            parts = f.parts
            if any(p.startswith('.') or p in self.config.excluded_dirs for p in parts):
                continue
            
            # Skip binary files (except PDFs which we want for whitepapers)
            if f.suffix.lower() in excluded_extensions:
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
            # Handle PDF files differently
            if file_path.suffix.lower() == '.pdf':
                # For PDFs, we'll store metadata and note that content extraction is needed
                content = f"[PDF Document: {file_path.name}]"
                metadata = {
                    "file_type": "pdf",
                    "requires_extraction": True,
                    "file_size": file_path.stat().st_size,
                    "note": "PDF content extraction required for full text"
                }
            else:
                # Read text file content
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
                
                metadata = {
                    "file_type": file_path.suffix or "no_extension",
                    "file_size": len(content),
                    "lines": content.count('\n') + 1
                }
            
            # Generate document metadata
            relative_path = file_path.relative_to(file_path.parent.parent.parent)
            
            # Construct GitLab URL (different format than GitHub)
            # GitLab uses /-/blob/ instead of /blob/
            file_url = f"{repo_url}/-/blob/{branch}/{relative_path}"
            
            # Generate RID
            rid = f"gitlab:{repo_name}:{relative_path}"
            rid = rid.replace('/', ':').replace(' ', '_')
            
            # Skip if already processed
            if rid in self.processed_rids:
                return None
            self.processed_rids.add(rid)
            
            # Extract publication date
            published_at = None
            confidence = 0.0
            
            # For markdown/text files, try to extract date from content
            if file_path.suffix in ['.md', '.mdx', '.txt']:
                import re
                # Look for date patterns
                date_pattern = r'date:\s*["\']*(\d{4}-\d{2}-\d{2})'
                match = re.search(date_pattern, content[:500] if isinstance(content, str) else "")
                if match:
                    try:
                        published_at = datetime.strptime(match.group(1), '%Y-%m-%d')
                        confidence = 0.8
                    except:
                        pass

            # Use git log to get last commit info for this file
            commit_message = None
            commit_author = None
            if not published_at:
                try:
                    # Get the last commit info for this file
                    # Format: commit date|author|subject|body
                    result = subprocess.run(
                        ['git', 'log', '-1', '--format=%cI|%an|%s|%b', str(file_path)],
                        cwd=file_path.parent.parent.parent,  # repo root
                        capture_output=True,
                        text=True
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        parts = result.stdout.strip().split('|', 3)
                        if len(parts) >= 1:
                            commit_date = parts[0]
                            published_at = datetime.fromisoformat(commit_date.replace('Z', '+00:00'))
                            confidence = 0.85  # High confidence for git commit dates
                        if len(parts) >= 2:
                            commit_author = parts[1]
                        if len(parts) >= 3:
                            # Combine subject and body
                            commit_message = parts[2]
                            if len(parts) >= 4 and parts[3].strip():
                                commit_message += "\n" + parts[3]
                except Exception as e:
                    self.logger.debug(f"Could not get git info for {file_path}: {e}")

            # Fallback to file modification time
            if not published_at:
                try:
                    import os
                    stat = os.stat(file_path)
                    published_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                    confidence = 0.6  # Lower confidence for file dates
                except:
                    pass
            
            # Add publication date metadata for Daily Curator
            metadata["published_at"] = published_at.isoformat() if published_at else None
            metadata["published_confidence"] = confidence

            # Add git commit metadata for context
            metadata["commit_message"] = commit_message
            metadata["commit_author"] = commit_author

            # Add collection timestamp
            metadata["collected_at"] = datetime.now(timezone.utc).isoformat()
            
            # Create document
            doc = {
                "rid": rid,
                "source": "gitlab",
                "repo": repo_name,
                "file_path": str(relative_path),
                "url": file_url,
                "branch": branch,
                "content": content,
                "metadata": metadata
            }
            
            # Special handling for whitepapers
            if "whitepaper" in str(file_path).lower() or "white-paper" in str(file_path).lower():
                doc["metadata"]["document_type"] = "whitepaper"
                doc["metadata"]["importance"] = "high"
            
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
                        self.config.koi_bridge_url,
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
                        self.documents_sent += 1
                    else:
                        self.logger.error(f"Failed to send {doc['rid']}: {response.status_code}")

            except Exception as e:
                self.logger.error(f"Error sending document {doc.get('rid', 'unknown')}: {e}")
                continue

        return success_count

    async def send_heartbeat_event(self, response_to: str = None):
        """Send a heartbeat event to register with coordinator"""
        heartbeat_data = {
            "type": "sensor_heartbeat",
            "sensor_id": "gitlab-sensor",
            "sensor_type": "gitlab",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "active",
            "monitoring": [repo["name"] for repo in self.config.repos],
            "documents_sent": self.documents_sent
        }

        if response_to:
            heartbeat_data["response_to"] = response_to

        # Create bundle
        bundle = {
            "rid": f"gitlab:heartbeat:{datetime.now().timestamp()}",
            "cid": hashlib.sha256(json.dumps(heartbeat_data).encode()).hexdigest(),
            "content": heartbeat_data,
            "metadata": {"type": "heartbeat"},
            "manifest": {
                "version": "1.0.0",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source": "gitlab-sensor"
            }
        }

        # Create event
        event = {
            "event_type": "HEARTBEAT",
            "source_sensor": "gitlab-sensor",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "bundle": bundle
        }

        # Send to coordinator
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.config.koi_coordinator_url}/events/broadcast",
                    json=event
                )
                if response.status_code == 200:
                    self.logger.info(f"Sent heartbeat to coordinator (response_to: {response_to})")
                else:
                    self.logger.error(f"Failed to send heartbeat: {response.status_code}")
        except Exception as e:
            self.logger.error(f"Error sending heartbeat: {e}")

    async def register_with_coordinator(self):
        """Register with coordinator on startup"""
        await self.send_heartbeat_event()
        self.logger.info("Registered with coordinator")

    async def send_periodic_heartbeats(self):
        """Send periodic heartbeats to stay registered"""
        while True:
            await asyncio.sleep(1800)  # Every 30 minutes
            await self.send_heartbeat_event()

    async def handle_coordinator_events(self):
        """Handle events from coordinator (ping requests)"""
        async with httpx.AsyncClient() as client:
            sse_url = f"{self.config.koi_coordinator_url}/events/stream?sensor_id=gitlab-sensor"
            try:
                async with client.stream('GET', sse_url) as response:
                    async for line in response.aiter_lines():
                        if line.startswith('data: '):
                            try:
                                event_data = json.loads(line[6:])
                                if event_data.get('event_type') == 'PING':
                                    self.logger.info("Received ping from coordinator")
                                    await self.send_heartbeat_event(response_to=event_data.get('ping_id'))
                            except json.JSONDecodeError:
                                continue
            except Exception as e:
                self.logger.error(f"Error handling coordinator events: {e}")

    def cleanup(self):
        """Clean up temporary directory"""
        try:
            if self.temp_dir.exists():
                shutil.rmtree(self.temp_dir)
                self.logger.info(f"Cleaned up temp directory: {self.temp_dir}")
        except Exception as e:
            self.logger.warning(f"Failed to clean up temp directory: {e}")


async def run_sensor_continuous(sensor):
    """Run sensor with continuous monitoring and heartbeats"""
    try:
        # Register with coordinator
        await sensor.register_with_coordinator()

        # Start background tasks
        heartbeat_task = asyncio.create_task(sensor.send_periodic_heartbeats())
        events_task = asyncio.create_task(sensor.handle_coordinator_events())

        while True:
            # Collect and send documents
            sensor.logger.info("Starting GitLab repository collection...")
            documents = await sensor.collect_all_repos()

            if documents:
                try:
                    success_count = await sensor.send_to_koi(documents)
                    sensor.logger.info(f"Successfully sent {success_count}/{len(documents)} documents to KOI")
                except Exception as e:
                    sensor.logger.warning(f"Could not send to KOI: {e}")

            # Wait before next collection (1 hour)
            await asyncio.sleep(3600)

    except KeyboardInterrupt:
        sensor.logger.info("Shutting down GitLab sensor...")
        heartbeat_task.cancel()
        events_task.cancel()
    except Exception as e:
        sensor.logger.error(f"Sensor error: {e}")
    finally:
        sensor.cleanup()


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
                "branch": "master",  # GitLab often uses master
                "paths": ["."]  # Get all documentation including whitepapers
            }
        ]
    )

    sensor = GitLabSensor(config, logger)

    # Run continuous monitoring with heartbeats
    await run_sensor_continuous(sensor)


if __name__ == "__main__":
    asyncio.run(main())