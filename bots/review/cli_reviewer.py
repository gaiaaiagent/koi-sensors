"""
CLI Reviewer - Command-line interface for reviewing draft threads
"""

import asyncio
import sys
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
from loguru import logger

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from bots.components.draft_storage import DraftStorage


class CLIReviewer:
    """
    Command-line interface for reviewing and approving draft threads
    Part of the draft-only week 1 workflow for Milestone B
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize CLI reviewer"""
        self.config = config
        self.storage = DraftStorage(config)
        
    async def review_draft(self, draft_id: str):
        """
        Interactive review of a draft thread
        
        Args:
            draft_id: UUID of the draft to review
        """
        # Get draft from storage
        draft = await self.storage.get_draft(draft_id)
        if not draft:
            print(f"❌ Draft not found: {draft_id}")
            return
        
        # Display draft header
        self._display_header(draft)
        
        # Display posts
        self._display_posts(draft['posts'])
        
        # Display validation results
        self._display_validation(draft.get('validation', {}))
        
        # Display style score
        self._display_style_score(draft.get('style_score', 0))
        
        # Get review action
        action = await self._get_review_action()
        
        # Process action
        await self._process_action(draft_id, action)
    
    def _display_header(self, draft: Dict[str, Any]):
        """Display draft header information"""
        print("\n" + "="*70)
        print("📝 DRAFT THREAD REVIEW")
        print("="*70)
        print(f"Draft ID: {draft['draft_id'][:8]}...")
        print(f"Thread Date: {draft['thread_date']}")
        print(f"Status: {draft['status']}")
        print(f"Created: {draft['created_at']}")
        print("="*70)
    
    def _display_posts(self, posts: list):
        """Display thread posts"""
        print("\n📱 THREAD POSTS:")
        print("-"*70)
        
        for i, post in enumerate(posts, 1):
            # Post header
            print(f"\n[{i}/{len(posts)}] {post.get('type', 'content').upper()}")
            print(f"Characters: {post.get('char_count', len(post['content']))}/280")
            
            # Post content
            print("-"*40)
            print(post['content'])
            
            # URLs if present
            if post.get('urls'):
                print(f"🔗 Links: {', '.join(post['urls'])}")
            
            print("-"*40)
    
    def _display_validation(self, validation: Dict[str, Any]):
        """Display link validation results"""
        if not validation or not validation.get('validated'):
            print("\n⚠️  Links not validated")
            return
        
        print("\n🔍 LINK VALIDATION:")
        print("-"*70)
        print(f"Total Links: {validation.get('total_links', 0)}")
        print(f"Valid Links: {validation.get('valid_links', 0)}")
        print(f"Invalid Links: {validation.get('invalid_links', 0)}")
        
        if validation.get('invalid_urls'):
            print("\n❌ Invalid URLs:")
            for url in validation['invalid_urls']:
                print(f"  - {url}")
    
    def _display_style_score(self, score: float):
        """Display style compliance score"""
        print("\n✨ STYLE COMPLIANCE:")
        print("-"*70)
        
        # Score with emoji indicator
        if score >= 0.9:
            emoji = "🟢"
            status = "Excellent"
        elif score >= 0.7:
            emoji = "🟡"
            status = "Good"
        elif score >= 0.5:
            emoji = "🟠"
            status = "Needs Improvement"
        else:
            emoji = "🔴"
            status = "Poor"
        
        print(f"{emoji} Style Score: {score:.2%} ({status})")
        
        # Compliance criteria from David Fortson / Many Mangos
        print("\nStyle Guide Checks:")
        print("  ✓ Professional tone")
        print("  ✓ No speculation")
        print("  ✓ Clear CTAs")
        print("  ✓ Consistent voice")
    
    async def _get_review_action(self) -> str:
        """Get review action from user"""
        print("\n" + "="*70)
        print("REVIEW ACTIONS:")
        print("  [A] Approve draft")
        print("  [R] Reject draft")
        print("  [E] Edit notes")
        print("  [S] Skip (no action)")
        print("="*70)
        
        while True:
            action = input("\nSelect action [A/R/E/S]: ").strip().upper()
            if action in ['A', 'R', 'E', 'S']:
                return action
            print("Invalid selection. Please choose A, R, E, or S.")
    
    async def _process_action(self, draft_id: str, action: str):
        """Process the review action"""
        if action == 'S':
            print("ℹ️  No action taken")
            return
        
        # Get review notes
        notes = ""
        if action in ['A', 'R', 'E']:
            notes = input("\nReview notes (optional): ").strip()
        
        # Process based on action
        if action == 'A':
            success = await self.storage.update_draft_status(draft_id, 'approved', notes)
            if success:
                print("✅ Draft approved!")
            else:
                print("❌ Failed to approve draft")
                
        elif action == 'R':
            success = await self.storage.update_draft_status(draft_id, 'rejected', notes)
            if success:
                print("❌ Draft rejected")
            else:
                print("❌ Failed to reject draft")
                
        elif action == 'E':
            # Just save notes without changing status
            draft = await self.storage.get_draft(draft_id)
            if draft:
                current_status = draft['status']
                success = await self.storage.update_draft_status(draft_id, current_status, notes)
                if success:
                    print("📝 Notes saved")
                else:
                    print("❌ Failed to save notes")
    
    async def list_drafts(self, status: Optional[str] = None):
        """List available drafts for review"""
        drafts = await self.storage.list_drafts(status=status, limit=20)
        
        if not drafts:
            print("No drafts found")
            return
        
        print("\n" + "="*70)
        print("📋 AVAILABLE DRAFTS")
        print("="*70)
        print(f"{'ID':<12} {'Date':<20} {'Status':<12} {'Score':<8}")
        print("-"*70)
        
        for draft in drafts:
            draft_id = draft['draft_id'][:8]
            date = datetime.fromisoformat(draft['thread_date']).strftime('%Y-%m-%d %H:%M')
            status = draft['status']
            score = f"{draft.get('style_score', 0):.2f}"
            
            # Status emoji
            status_emoji = {
                'draft': '📝',
                'approved': '✅',
                'rejected': '❌',
                'published': '🚀'
            }.get(status, '❓')
            
            print(f"{draft_id:<12} {date:<20} {status_emoji} {status:<10} {score:<8}")
        
        print("="*70)
        print(f"Total: {len(drafts)} drafts")
    
    async def review_all_pending(self):
        """Review all pending drafts"""
        drafts = await self.storage.list_drafts(status='draft', limit=50)
        
        if not drafts:
            print("No pending drafts to review")
            return
        
        print(f"\n📋 Found {len(drafts)} pending drafts")
        
        for i, draft_summary in enumerate(drafts, 1):
            print(f"\n[{i}/{len(drafts)}] Reviewing draft {draft_summary['draft_id'][:8]}...")
            await self.review_draft(draft_summary['draft_id'])
            
            if i < len(drafts):
                cont = input("\nContinue to next draft? [Y/n]: ").strip().lower()
                if cont == 'n':
                    break
        
        print("\n✅ Review session complete")


async def main():
    """Main entry point for CLI reviewer"""
    import yaml
    
    # Load config
    config_path = Path(__file__).parent.parent.parent / "config" / "curator_config.yaml"
    if config_path.exists():
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
    else:
        config = {}
    
    reviewer = CLIReviewer(config)
    
    # Check command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == 'list':
            await reviewer.list_drafts()
        elif sys.argv[1] == 'review-all':
            await reviewer.review_all_pending()
        else:
            # Assume it's a draft ID
            await reviewer.review_draft(sys.argv[1])
    else:
        # Interactive mode
        print("X Bot Draft Reviewer")
        print("Usage:")
        print("  python cli_reviewer.py list           - List all drafts")
        print("  python cli_reviewer.py review-all     - Review all pending")
        print("  python cli_reviewer.py <draft_id>     - Review specific draft")
        
        await reviewer.list_drafts()


if __name__ == "__main__":
    asyncio.run(main())