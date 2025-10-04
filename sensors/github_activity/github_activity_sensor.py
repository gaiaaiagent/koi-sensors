"""
KOI GitHub Activity Sensor - Captures commits, issues, PRs, and discussions
Uses GitHub API to monitor repository activity
"""

import asyncio
import httpx
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import hashlib

# Add parent directories to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.rid_system import RID
from koi_protocol.core.bundle_system import document_to_bundle

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('github_activity.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class GitHubActivityConfig:
    """GitHub activity sensor configuration"""
    repos: List[Dict[str, Any]]
    github_token: Optional[str] = None  # Optional GitHub token for higher rate limits
    coordinator_url: str = "http://localhost:8005"
    source_sensor: str = "github-activity-sensor"
    lookback_hours: int = 24  # How far back to look for activity

class GitHubActivitySensor:
    def __init__(self, config: GitHubActivityConfig):
        self.config = config
        self.koi_node = KOIPartialNode(
            node_name=config.source_sensor,
            coordinator_url=config.coordinator_url
        )
        self.processed_items = set()
        self.headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'KOI-GitHub-Activity-Sensor'
        }
        if config.github_token:
            self.headers['Authorization'] = f'token {config.github_token}'

    async def fetch_github_api(self, url: str) -> Optional[Dict]:
        """Fetch data from GitHub API"""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self.headers)
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.warning(f"GitHub API returned {response.status_code} for {url}")
                    return None
            except Exception as e:
                logger.error(f"Error fetching {url}: {e}")
                return None

    async def get_recent_commits(self, owner: str, repo: str) -> List[Dict]:
        """Get recent commits from the repository"""
        since = (datetime.now(timezone.utc) - timedelta(hours=self.config.lookback_hours)).isoformat()
        url = f"https://api.github.com/repos/{owner}/{repo}/commits?since={since}"

        commits = await self.fetch_github_api(url)
        if not commits:
            return []

        documents = []
        for commit in commits[:10]:  # Limit to 10 most recent
            commit_sha = commit['sha'][:8]
            commit_key = f"{owner}/{repo}/commit/{commit_sha}"

            if commit_key in self.processed_items:
                continue

            # Create RID for the commit
            rid = f"github.commit:{owner}_{repo}_{commit_sha}"

            # Extract commit details
            author = commit.get('commit', {}).get('author', {})
            commit_date = author.get('date', datetime.now(timezone.utc).isoformat())

            document = {
                'id': commit_key,
                'rid': rid,
                'source': f'github:{owner}/{repo}',
                'source_type': 'commit',
                'url': commit.get('html_url', f"https://github.com/{owner}/{repo}/commit/{commit['sha']}"),
                'title': f"Commit: {commit.get('commit', {}).get('message', '').split('\\n')[0][:100]}",
                'content': commit.get('commit', {}).get('message', ''),
                'author': author.get('name', 'Unknown'),
                'timestamp': commit_date,
                'metadata': {
                    'published_at': commit_date,
                    'published_confidence': 1.0,
                    'commit_sha': commit['sha'],
                    'author_email': author.get('email'),
                    'stats': commit.get('stats', {}),
                    'files_changed': len(commit.get('files', [])) if 'files' in commit else None
                }
            }

            documents.append(document)
            self.processed_items.add(commit_key)

        return documents

    async def get_recent_issues(self, owner: str, repo: str) -> List[Dict]:
        """Get recent issues and issue comments"""
        since = (datetime.now(timezone.utc) - timedelta(hours=self.config.lookback_hours)).isoformat()

        # Get recently updated issues
        url = f"https://api.github.com/repos/{owner}/{repo}/issues?state=all&since={since}&sort=updated"

        issues = await self.fetch_github_api(url)
        if not issues:
            return []

        documents = []
        for issue in issues[:10]:  # Limit to 10 most recent
            issue_key = f"{owner}/{repo}/issue/{issue['number']}"

            if issue_key in self.processed_items:
                continue

            # Create RID for the issue
            rid = f"github.issue:{owner}_{repo}_{issue['number']}"

            document = {
                'id': issue_key,
                'rid': rid,
                'source': f'github:{owner}/{repo}',
                'source_type': 'issue',
                'url': issue['html_url'],
                'title': issue['title'],
                'content': issue.get('body', ''),
                'author': issue.get('user', {}).get('login', 'Unknown'),
                'timestamp': issue['updated_at'],
                'metadata': {
                    'published_at': issue['created_at'],
                    'updated_at': issue['updated_at'],
                    'published_confidence': 1.0,
                    'issue_number': issue['number'],
                    'state': issue['state'],
                    'labels': [label['name'] for label in issue.get('labels', [])],
                    'comments_count': issue.get('comments', 0),
                    'is_pull_request': 'pull_request' in issue
                }
            }

            documents.append(document)
            self.processed_items.add(issue_key)

        return documents

    async def get_recent_pulls(self, owner: str, repo: str) -> List[Dict]:
        """Get recent pull requests"""
        # Get recently updated PRs
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls?state=all&sort=updated&direction=desc"

        pulls = await self.fetch_github_api(url)
        if not pulls:
            return []

        # Filter to only those updated recently
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.config.lookback_hours)

        documents = []
        for pr in pulls[:10]:  # Limit to 10
            updated = datetime.fromisoformat(pr['updated_at'].replace('Z', '+00:00'))
            if updated < cutoff:
                continue

            pr_key = f"{owner}/{repo}/pr/{pr['number']}"

            if pr_key in self.processed_items:
                continue

            # Create RID for the PR
            rid = f"github.pr:{owner}_{repo}_{pr['number']}"

            document = {
                'id': pr_key,
                'rid': rid,
                'source': f'github:{owner}/{repo}',
                'source_type': 'pull_request',
                'url': pr['html_url'],
                'title': pr['title'],
                'content': pr.get('body', ''),
                'author': pr.get('user', {}).get('login', 'Unknown'),
                'timestamp': pr['updated_at'],
                'metadata': {
                    'published_at': pr['created_at'],
                    'updated_at': pr['updated_at'],
                    'published_confidence': 1.0,
                    'pr_number': pr['number'],
                    'state': pr['state'],
                    'merged': pr.get('merged', False),
                    'merged_at': pr.get('merged_at'),
                    'head_ref': pr.get('head', {}).get('ref'),
                    'base_ref': pr.get('base', {}).get('ref'),
                    'commits': pr.get('commits', 0),
                    'additions': pr.get('additions', 0),
                    'deletions': pr.get('deletions', 0)
                }
            }

            documents.append(document)
            self.processed_items.add(pr_key)

        return documents

    async def get_recent_discussions(self, owner: str, repo: str) -> List[Dict]:
        """Get recent discussions (requires GraphQL API)"""
        # Note: Discussions require GraphQL API which is more complex
        # For now, returning empty list - can be implemented if needed
        logger.info(f"Discussions API not yet implemented for {owner}/{repo}")
        return []

    async def collect_repo_activity(self, repo_config: Dict) -> List[Dict]:
        """Collect all activity from a repository"""
        owner = repo_config['owner']
        repo = repo_config['name']

        logger.info(f"Collecting activity from {owner}/{repo}")

        all_documents = []

        # Collect different types of activity in parallel
        commits, issues, pulls = await asyncio.gather(
            self.get_recent_commits(owner, repo),
            self.get_recent_issues(owner, repo),
            self.get_recent_pulls(owner, repo)
        )

        all_documents.extend(commits)
        all_documents.extend(issues)
        all_documents.extend(pulls)

        logger.info(f"Found {len(commits)} commits, {len(issues)} issues, {len(pulls)} PRs in {owner}/{repo}")

        return all_documents

    async def send_to_coordinator(self, documents: List[Dict]):
        """Send documents to KOI coordinator"""
        for doc in documents:
            try:
                # Create bundle from document
                bundle = document_to_bundle(
                    doc,
                    source_node=self.config.source_sensor
                )

                # Send to coordinator
                await self.koi_node.emit_new_event(bundle)
                logger.info(f"✓ Sent {doc['source_type']}: {doc['id']}")

            except Exception as e:
                logger.error(f"Error processing document {doc.get('id')}: {e}")

    async def run_once(self):
        """Run one collection cycle"""
        logger.info("Starting GitHub activity collection cycle")

        all_documents = []
        for repo_config in self.config.repos:
            try:
                documents = await self.collect_repo_activity(repo_config)
                all_documents.extend(documents)
            except Exception as e:
                logger.error(f"Error collecting from {repo_config}: {e}")

        if all_documents:
            logger.info(f"Sending {len(all_documents)} documents to coordinator")
            await self.send_to_coordinator(all_documents)

        logger.info("Collection cycle complete")

    async def run(self):
        """Run the sensor continuously"""
        logger.info("GitHub Activity Sensor starting...")

        # Start KOI node
        await self.koi_node.start()

        while True:
            try:
                await self.run_once()

                # Wait before next cycle (check every 30 minutes)
                await asyncio.sleep(1800)

            except KeyboardInterrupt:
                logger.info("Shutting down...")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                await asyncio.sleep(60)  # Wait a minute on error

async def main():
    """Main entry point"""

    # Load configuration
    config_path = Path(__file__).parent / "config.yaml"

    if not config_path.exists():
        logger.error(f"Config file not found: {config_path}")
        return

    import yaml
    with open(config_path) as f:
        config_data = yaml.safe_load(f)

    # Check for GitHub token in environment
    github_token = os.getenv('GITHUB_TOKEN')
    if github_token:
        logger.info("Using GitHub token from environment")
    else:
        logger.warning("No GitHub token found - API rate limits will be lower")

    config = GitHubActivityConfig(
        repos=config_data.get('repos', []),
        github_token=github_token,
        coordinator_url=config_data.get('koi_coordinator_url', 'http://localhost:8005'),
        source_sensor='github-activity-sensor',
        lookback_hours=config_data.get('lookback_hours', 24)
    )

    sensor = GitHubActivitySensor(config)
    await sensor.run()

if __name__ == "__main__":
    asyncio.run(main())