"""
X Daily Bot - Main orchestrator for creating Twitter/X draft threads
Consumes Daily Curator output and creates "Regen Daily" posts
"""

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from loguru import logger
import yaml

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from bots.components.thread_composer import ThreadComposer
from bots.components.link_validator import LinkValidator
from bots.components.style_enforcer import StyleEnforcer
from bots.components.draft_storage import DraftStorage


class XDailyBot:
    """
    Main bot class for generating X/Twitter draft threads from Daily Curator output
    Implements Milestone B requirements for "Regen Daily" posts
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize the X Daily Bot with configuration"""
        # Load configuration
        self.config = self._load_config(config_path)
        
        # Initialize components
        self.composer = ThreadComposer(self.config)
        self.validator = LinkValidator(self.config)
        self.style_enforcer = StyleEnforcer(self.config)
        self.storage = DraftStorage(self.config)
        
        # Bot settings
        self.draft_mode = self.config.get('x_bot', {}).get('draft_mode', True)
        self.draft_days = self.config.get('x_bot', {}).get('draft_days', 7)
        
        logger.info(f"X Daily Bot initialized (draft_mode={self.draft_mode})")
    
    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        if not config_path:
            # Try multiple default locations
            config_locations = [
                Path(__file__).parent.parent.parent / "koi-processor" / "config" / "curator_config.yaml",
                Path(__file__).parent / "config" / "x_bot_config.yaml",
                Path(__file__).parent.parent / "config" / "curator_config.yaml"
            ]
            
            for location in config_locations:
                if location.exists():
                    config_path = str(location)
                    break
        
        if config_path and Path(config_path).exists():
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                logger.info(f"Loaded config from {config_path}")
                return config
        else:
            logger.warning("No config file found, using defaults")
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Return default configuration"""
        return {
            'x_bot': {
                'draft_mode': True,
                'draft_days': 7,
                'style_guide': {
                    'tone': 'professional_friendly',
                    'use_thread_numbers': True,
                    'default_cta': 'Learn more at regen.network',
                    'max_tweet_length': 280
                },
                'hashtags': ['#RegenNetwork', '#ReFi'],
                'validation': {
                    'check_links': True,
                    'no_speculation': True,
                    'require_sources': True
                }
            },
            'database_url': 'postgresql://postgres:postgres@localhost:5433/eliza',
            'output': {
                'daily_thread_path': 'output/daily_threads/',
                'draft_path': 'bots/drafts/'
            }
        }
    
    async def process_curator_output(self, curator_output_path: str) -> Dict[str, Any]:
        """
        Process a Daily Curator output file and generate draft thread
        
        Args:
            curator_output_path: Path to curator JSON output
            
        Returns:
            Draft thread with metadata and validation results
        """
        logger.info(f"Processing curator output: {curator_output_path}")
        
        # Load curator output
        with open(curator_output_path, 'r') as f:
            curator_data = json.load(f)
        
        # Step 1: Compose thread from curator data
        thread = self.composer.compose_thread(curator_data)
        logger.info(f"Composed thread with {len(thread['posts'])} posts")
        
        # Step 2: Validate links in thread
        validation_results = await self.validator.validate_thread(thread)
        thread['validation'] = validation_results
        logger.info(f"Link validation: {validation_results['valid_links']}/{validation_results['total_links']} valid")
        
        # Step 3: Apply style guide enforcement
        styled_thread = self.style_enforcer.enforce_style(thread)
        logger.info(f"Style score: {styled_thread['style_score']:.2f}")
        
        # Step 4: Store draft
        draft_id = await self.storage.save_draft(
            styled_thread,
            curator_data,
            status='draft' if self.draft_mode else 'ready'
        )
        styled_thread['draft_id'] = draft_id
        logger.info(f"Saved draft with ID: {draft_id}")
        
        return styled_thread
    
    async def generate_drafts_from_directory(self, directory_path: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Generate drafts from all curator outputs in a directory
        
        Args:
            directory_path: Directory containing curator JSON files
            limit: Maximum number of drafts to generate
            
        Returns:
            List of generated draft threads
        """
        directory = Path(directory_path)
        if not directory.exists():
            logger.error(f"Directory not found: {directory_path}")
            return []
        
        # Find curator output files
        curator_files = sorted(directory.glob("*.json"))[:limit]
        logger.info(f"Found {len(curator_files)} curator output files")
        
        drafts = []
        for curator_file in curator_files:
            try:
                draft = await self.process_curator_output(str(curator_file))
                drafts.append(draft)
                logger.info(f"Generated draft {len(drafts)}/{limit}")
            except Exception as e:
                logger.error(f"Failed to process {curator_file}: {e}")
        
        return drafts
    
    async def review_draft(self, draft_id: str) -> Dict[str, Any]:
        """
        Retrieve a draft for review
        
        Args:
            draft_id: UUID of the draft
            
        Returns:
            Draft data with formatted preview
        """
        draft = await self.storage.get_draft(draft_id)
        if not draft:
            logger.error(f"Draft not found: {draft_id}")
            return None
        
        # Format for review
        review_data = {
            'draft_id': draft_id,
            'thread_date': draft['thread_date'],
            'status': draft['status'],
            'posts': draft['posts'],
            'validation': draft.get('validation', {}),
            'style_score': draft.get('style_score', 0),
            'preview': self._format_preview(draft['posts'])
        }
        
        return review_data
    
    def _format_preview(self, posts: List[Dict[str, Any]]) -> str:
        """Format posts as a text preview"""
        preview_lines = []
        for i, post in enumerate(posts, 1):
            preview_lines.append(f"--- Tweet {i}/{len(posts)} ---")
            preview_lines.append(post['content'])
            preview_lines.append(f"Characters: {post.get('char_count', len(post['content']))}")
            if post.get('urls'):
                preview_lines.append(f"Links: {', '.join(post['urls'])}")
            preview_lines.append("")
        
        return "\n".join(preview_lines)
    
    async def approve_draft(self, draft_id: str, notes: str = "") -> bool:
        """
        Approve a draft for publishing
        
        Args:
            draft_id: UUID of the draft
            notes: Review notes
            
        Returns:
            Success status
        """
        return await self.storage.update_draft_status(draft_id, 'approved', notes)
    
    async def reject_draft(self, draft_id: str, notes: str = "") -> bool:
        """
        Reject a draft
        
        Args:
            draft_id: UUID of the draft
            notes: Rejection reason
            
        Returns:
            Success status
        """
        return await self.storage.update_draft_status(draft_id, 'rejected', notes)


async def main():
    """Main entry point for testing the X Daily Bot"""
    bot = XDailyBot()
    
    # Test with sample curator output
    test_path = Path(__file__).parent.parent.parent / "koi-processor" / "output" / "daily_threads"
    
    if test_path.exists():
        # Process existing curator outputs
        drafts = await bot.generate_drafts_from_directory(str(test_path), limit=5)
        logger.info(f"Generated {len(drafts)} draft threads")
        
        # Review first draft
        if drafts:
            first_draft = drafts[0]
            review = await bot.review_draft(first_draft['draft_id'])
            if review:
                print("\n" + "="*60)
                print("DRAFT PREVIEW")
                print("="*60)
                print(review['preview'])
                print("="*60)
                print(f"Style Score: {review['style_score']:.2f}")
                print(f"Valid Links: {review['validation'].get('valid_links', 0)}/{review['validation'].get('total_links', 0)}")
    else:
        logger.warning(f"No curator outputs found in {test_path}")
        logger.info("Please run the Daily Curator first to generate content")


if __name__ == "__main__":
    asyncio.run(main())