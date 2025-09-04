"""
Git repository collector for GitHub and GitLab sources
"""

import asyncio
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime
import tempfile
import shutil
from git import Repo
from loguru import logger

from .base_collector import BaseCollector, Document


class GitCollector(BaseCollector):
    """
    Collector for Git repositories (GitHub, GitLab, etc.)
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Git collector
        
        Args:
            config: Repository configuration from sources.yaml
        """
        super().__init__(config)
        self.repos = config.get('repos', [])
        self.temp_dir = Path(tempfile.mkdtemp(prefix="git_collector_"))
        logger.info(f"Using temp directory: {self.temp_dir}")
    
    def validate_config(self) -> bool:
        """
        Validate Git collector configuration
        """
        if not self.repos:
            logger.error("No repositories configured")
            return False
        
        for repo in self.repos:
            if 'url' not in repo:
                logger.error(f"Repository missing URL: {repo}")
                return False
            if 'name' not in repo:
                logger.error(f"Repository missing name: {repo}")
                return False
        
        return True
    
    async def collect(self, limit: Optional[int] = None) -> List[Document]:
        """
        Collect documents from configured Git repositories
        
        Args:
            limit: Maximum number of documents to collect
            
        Returns:
            List of collected documents
        """
        if not self.validate_config():
            return []
        
        all_documents = []
        doc_count = 0
        
        for repo_config in self.repos:
            if limit and doc_count >= limit:
                break
                
            try:
                repo_docs = await self.collect_repo(
                    repo_config, 
                    limit - doc_count if limit else None
                )
                all_documents.extend(repo_docs)
                doc_count += len(repo_docs)
                
                # Save documents after each repo
                self.save_documents(repo_docs)
                
            except Exception as e:
                logger.error(f"Error collecting repo {repo_config['name']}: {e}")
                continue
        
        logger.info(f"Collected {len(all_documents)} documents from {len(self.repos)} repositories")
        return all_documents
    
    async def collect_repo(self, repo_config: Dict[str, Any], limit: Optional[int] = None) -> List[Document]:
        """
        Collect documents from a single repository
        
        Args:
            repo_config: Repository configuration
            limit: Maximum number of documents to collect
            
        Returns:
            List of documents from the repository
        """
        repo_name = repo_config['name']
        repo_url = repo_config['url']
        branch = repo_config.get('branch', 'main')
        paths = repo_config.get('paths', ['.'])
        
        logger.info(f"Collecting from {repo_name} ({repo_url})")
        
        # Clone repository to temp directory
        repo_path = self.temp_dir / repo_name
        if repo_path.exists():
            shutil.rmtree(repo_path)
        
        try:
            logger.debug(f"Cloning {repo_url} to {repo_path}")
            repo = Repo.clone_from(repo_url, repo_path, branch=branch, depth=1)
        except Exception as e:
            # Try with 'master' branch if 'main' fails
            if branch == 'main':
                try:
                    logger.debug(f"Retrying with master branch")
                    repo = Repo.clone_from(repo_url, repo_path, branch='master', depth=1)
                except Exception as e2:
                    logger.error(f"Failed to clone {repo_url}: {e2}")
                    return []
            else:
                logger.error(f"Failed to clone {repo_url}: {e}")
                return []
        
        documents = []
        doc_count = 0
        
        # Process specified paths
        for path_pattern in paths:
            if limit and doc_count >= limit:
                break
                
            files = self.find_files(repo_path, path_pattern)
            
            for file_path in files:
                if limit and doc_count >= limit:
                    break
                
                # Skip if already cached
                relative_path = file_path.relative_to(repo_path)
                file_url = f"{repo_url}/blob/{branch}/{relative_path}"
                
                if self.is_cached(file_url):
                    logger.debug(f"Skipping cached file: {relative_path}")
                    continue
                
                doc = self.process_file(file_path, repo_name, repo_url, branch)
                if doc:
                    documents.append(doc)
                    doc_count += 1
        
        # Clean up cloned repo
        try:
            shutil.rmtree(repo_path)
        except Exception as e:
            logger.warning(f"Failed to clean up {repo_path}: {e}")
        
        logger.info(f"Collected {len(documents)} documents from {repo_name}")
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
        
        # Extended list of documentation file types
        doc_extensions = [
            '*.md', '*.MD', '*.mdx',  # Markdown
            '*.rst', '*.txt', '*.asciidoc',  # Other docs
            '*.json', '*.yaml', '*.yml',  # Config/API specs
            '*.toml', '*.ini', '*.cfg',  # Config files
            'LICENSE*', 'COPYRIGHT*', 'NOTICE*',  # Legal docs
            'README*', 'CHANGELOG*', 'CONTRIBUTING*'  # Common docs without extension
        ]
        
        # Handle different pattern types
        if pattern == '.':
            # All documentation files recursively
            for ext in doc_extensions:
                files.extend(repo_path.glob(f'**/{ext}'))
        elif '*' in pattern:
            # Glob pattern
            files.extend(repo_path.glob(pattern))
        else:
            # Specific directory or file
            target = repo_path / pattern
            if target.is_dir():
                # Search for all doc types in directory
                for ext in doc_extensions:
                    files.extend(target.glob(f'**/{ext}'))
            elif target.exists():
                files.append(target)
        
        # Filter out common non-documentation files
        filtered_files = []
        excluded_dirs = ['node_modules', 'vendor', 'dist', 'build', '.git', 
                        '__pycache__', '.pytest_cache', 'coverage', '.next', 
                        'out', 'target', 'bin', '.vscode', '.idea']
        
        for f in files:
            # Skip hidden files and excluded directories
            parts = f.parts
            if any(p.startswith('.') or p in excluded_dirs for p in parts):
                continue
            
            # Skip binary and media files
            if f.suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico',
                                   '.pdf', '.zip', '.tar', '.gz', '.bz2', '.exe', 
                                   '.dll', '.so', '.dylib', '.woff', '.ttf', '.eot']:
                continue
            
            # Skip test fixtures and mocks (but keep test documentation)
            if 'fixtures' in str(f) or 'mocks' in str(f) or '__mocks__' in str(f):
                continue
                
            filtered_files.append(f)
        
        # Log if we're truncating
        if len(filtered_files) > 1000:
            logger.warning(f"Found {len(filtered_files)} files matching '{pattern}', processing all of them")
        
        return filtered_files  # No artificial limit - we need all docs
    
    def process_file(self, file_path: Path, repo_name: str, repo_url: str, branch: str) -> Optional[Document]:
        """
        Process a single file into a Document
        
        Args:
            file_path: Path to file
            repo_name: Repository name
            repo_url: Repository URL
            branch: Git branch
            
        Returns:
            Document object or None if processing fails
        """
        try:
            # Read file content
            try:
                content = file_path.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                # Try latin-1 encoding as fallback
                content = file_path.read_text(encoding='latin-1')
            
            # Skip empty or very small files
            if len(content.strip()) < 50:
                return None
            
            # Get file metadata - calculate relative path from repo root
            repo_root = file_path
            # Find the repo root by looking for the repo name in the path
            for parent in file_path.parents:
                if parent.name == repo_name:
                    repo_root = parent
                    break
            
            # Calculate relative path from repo root
            try:
                relative_path = file_path.relative_to(repo_root)
            except ValueError:
                # Fallback if repo root not found
                relative_path = Path(file_path.name)
            
            # Create proper GitHub URL
            file_url = f"{repo_url.rstrip('.git')}/blob/{branch}/{relative_path.as_posix()}"
            
            # Extract title from content or filename
            title = self.extract_title(content, file_path.name)
            
            # Get file modification time
            last_modified = datetime.fromtimestamp(file_path.stat().st_mtime)
            
            # Create Document
            doc = Document(
                id="",  # Will be auto-generated
                source=f"github:{repo_name}",
                source_type="github",
                url=file_url,
                title=title,
                content=content,
                metadata={
                    "repository": repo_name,
                    "branch": branch,
                    "file_path": relative_path.as_posix(),
                    "file_type": file_path.suffix.lower(),
                    "size_bytes": len(content)
                },
                last_modified=last_modified,
                tags=self.extract_tags(content, repo_name)
            )
            
            logger.debug(f"Processed: {relative_path.as_posix()} ({len(content)} bytes)")
            return doc
            
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
            return None
    
    def extract_title(self, content: str, filename: str) -> str:
        """
        Extract title from document content or filename
        
        Args:
            content: Document content
            filename: File name
            
        Returns:
            Extracted title
        """
        # Try to extract from markdown header
        lines = content.split('\n')
        for line in lines[:10]:  # Check first 10 lines
            if line.startswith('# '):
                return line[2:].strip()
        
        # Use filename without extension as fallback
        return Path(filename).stem.replace('-', ' ').replace('_', ' ').title()
    
    def extract_tags(self, content: str, repo_name: str) -> List[str]:
        """
        Extract relevant tags from document content
        
        Args:
            content: Document content
            repo_name: Repository name
            
        Returns:
            List of tags
        """
        tags = [repo_name]
        
        # Add tags based on content keywords
        keywords = {
            'ecocredit': ['carbon', 'credit', 'climate', 'offset'],
            'governance': ['proposal', 'vote', 'dao', 'governance'],
            'token': ['regen', 'token', 'tokenomics', 'staking'],
            'technical': ['api', 'sdk', 'contract', 'module', 'cosmos'],
            'guide': ['tutorial', 'guide', 'how-to', 'setup']
        }
        
        content_lower = content.lower()
        for tag, terms in keywords.items():
            if any(term in content_lower for term in terms):
                tags.append(tag)
        
        return list(set(tags))  # Remove duplicates
    
    def __del__(self):
        """
        Clean up temporary directory on deletion
        """
        if hasattr(self, 'temp_dir') and self.temp_dir.exists():
            try:
                shutil.rmtree(self.temp_dir)
                logger.debug(f"Cleaned up temp directory: {self.temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp directory: {e}")