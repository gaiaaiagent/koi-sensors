"""
Generate test data for X Bot Draft Generator
Creates sample curator outputs for testing thread generation
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List
import random

# Add parent directories to path
sys.path.append(str(Path(__file__).parent.parent.parent))


def generate_sample_curator_output(scenario: str = "standard") -> Dict[str, Any]:
    """
    Generate a sample curator output for testing
    
    Args:
        scenario: Type of scenario (standard, governance, credits, community, minimal)
        
    Returns:
        Sample curator output matching the daily_curator.py format
    """
    base_time = datetime.now(timezone.utc)
    
    if scenario == "governance":
        posts = [
            {
                "type": "headline",
                "content": "Regen Network Daily Update",
                "metadata": {"priority": "high", "position": 1}
            },
            {
                "type": "stat",
                "content": "📊 Network Stats:\n• 3 new governance proposals\n• 87% voting participation\n• 2.4M REGEN staked",
                "source": "ledger_sensor",
                "published_at": base_time.isoformat(),
                "metadata": {"position": 2}
            },
            {
                "type": "link",
                "content": "New proposal for credit class methodology update now open for voting",
                "url": "https://forum.regen.network/t/proposal-42-credit-methodology",
                "source": "discourse",
                "published_at": (base_time - timedelta(hours=2)).isoformat(),
                "metadata": {"position": 3}
            },
            {
                "type": "link",
                "content": "Community discussion on governance participation rewards gaining traction",
                "url": "https://forum.regen.network/t/governance-rewards-discussion",
                "source": "discourse",
                "published_at": (base_time - timedelta(hours=5)).isoformat(),
                "metadata": {"position": 4}
            },
            {
                "type": "cta",
                "content": "Join the governance discussion at forum.regen.network",
                "metadata": {"position": 5}
            }
        ]
        
    elif scenario == "credits":
        posts = [
            {
                "type": "headline",
                "content": "Regen Network Daily Update - Ecocredit Focus",
                "metadata": {"priority": "high", "position": 1}
            },
            {
                "type": "stat",
                "content": "🌿 Ecocredit Activity:\n• 2 new credit batches issued\n• 10,000 credits retired\n• 5 new projects registered",
                "source": "ledger_sensor",
                "published_at": base_time.isoformat(),
                "metadata": {"position": 2}
            },
            {
                "type": "link",
                "content": "New biodiversity credit class C04 launched with innovative methodology",
                "url": "https://registry.regen.network/credit-classes/C04",
                "source": "website",
                "published_at": (base_time - timedelta(hours=1)).isoformat(),
                "metadata": {"position": 3}
            },
            {
                "type": "link",
                "content": "Case study: How regenerative farming increased soil carbon by 30%",
                "url": "https://medium.com/regen-network/soil-carbon-case-study",
                "source": "medium",
                "published_at": (base_time - timedelta(hours=12)).isoformat(),
                "metadata": {"position": 4}
            },
            {
                "type": "cta",
                "content": "Explore credit classes at registry.regen.network",
                "metadata": {"position": 5}
            }
        ]
        
    elif scenario == "community":
        posts = [
            {
                "type": "headline",
                "content": "Regen Network Community Update",
                "metadata": {"priority": "high", "position": 1}
            },
            {
                "type": "stat",
                "content": "💚 Community Growth:\n• 500+ new Discord members\n• 15 community calls this month\n• 8 new validator nodes",
                "source": "ledger_sensor",
                "published_at": base_time.isoformat(),
                "metadata": {"position": 2}
            },
            {
                "type": "link",
                "content": "Recording from yesterday's community call on regenerative finance now available",
                "url": "https://regen.network/community-calls/episode-23",
                "source": "podcast",
                "published_at": (base_time - timedelta(hours=20)).isoformat(),
                "metadata": {"position": 3}
            },
            {
                "type": "cta",
                "content": "Join our Discord community at discord.gg/regen",
                "metadata": {"position": 4}
            }
        ]
        
    elif scenario == "minimal":
        posts = [
            {
                "type": "headline",
                "content": "Regen Network Update",
                "metadata": {"priority": "high", "position": 1}
            },
            {
                "type": "stat",
                "content": "Network operating normally. All systems functional.",
                "source": "ledger_sensor",
                "published_at": base_time.isoformat(),
                "metadata": {"position": 2}
            }
        ]
        
    else:  # standard
        posts = [
            {
                "type": "headline",
                "content": "Regen Network Daily Update",
                "metadata": {"priority": "high", "position": 1}
            },
            {
                "type": "stat",
                "content": "📊 Today's Highlights:\n• 1 new proposal\n• 5,000 credits retired\n• Network uptime: 99.9%",
                "source": "ledger_sensor",
                "published_at": base_time.isoformat(),
                "metadata": {"position": 2}
            },
            {
                "type": "link",
                "content": "Technical update: New features added to Regen Ledger v5.0",
                "url": "https://github.com/regen-network/regen-ledger/releases/v5.0",
                "source": "github",
                "published_at": (base_time - timedelta(hours=3)).isoformat(),
                "metadata": {"position": 3}
            },
            {
                "type": "link",
                "content": "Blog post: The future of regenerative finance in 2025",
                "url": "https://medium.com/regen-network/refi-future-2025",
                "source": "medium",
                "published_at": (base_time - timedelta(hours=8)).isoformat(),
                "metadata": {"position": 4}
            },
            {
                "type": "cta",
                "content": "Learn more at regen.network",
                "metadata": {"position": 5}
            }
        ]
    
    # Build complete curator output
    curator_output = {
        "thread_date": base_time.isoformat(),
        "posts": posts,
        "metadata": {
            "content_sources": {
                "new_today": random.randint(5, 15),
                "recent_48h": random.randint(20, 50),
                "trending_topics": random.randint(3, 8)
            },
            "stats": {
                "new_proposals": random.randint(0, 3),
                "new_batches": random.randint(0, 5),
                "new_credits": random.randint(1000, 50000),
                "marketplace_volume": random.randint(10000, 100000),
                "active_proposals": random.randint(1, 5)
            },
            "scenario": scenario,
            "generated_for_testing": True
        }
    }
    
    return curator_output


def generate_test_files(output_dir: str = None) -> List[str]:
    """
    Generate test curator output files for different scenarios
    
    Args:
        output_dir: Directory to save test files (default: koi-processor/output/daily_threads)
        
    Returns:
        List of generated file paths
    """
    if not output_dir:
        output_dir = Path(__file__).parent.parent.parent.parent / "koi-processor" / "output" / "daily_threads"
    else:
        output_dir = Path(output_dir)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    scenarios = ["standard", "governance", "credits", "community", "minimal"]
    generated_files = []
    
    for i, scenario in enumerate(scenarios):
        # Generate curator output
        curator_output = generate_sample_curator_output(scenario)
        
        # Adjust thread date to make them appear as different days
        thread_date = datetime.now(timezone.utc) - timedelta(days=i)
        curator_output["thread_date"] = thread_date.isoformat()
        
        # Save to file
        filename = f"test_curator_{scenario}_{thread_date.strftime('%Y%m%d')}.json"
        file_path = output_dir / filename
        
        with open(file_path, 'w') as f:
            json.dump(curator_output, f, indent=2, default=str)
        
        print(f"✅ Generated: {file_path}")
        generated_files.append(str(file_path))
    
    return generated_files


def main():
    """Main entry point for test data generation"""
    print("🧪 Generating Test Data for X Bot Draft Generator")
    print("="*60)
    
    # Generate test files
    files = generate_test_files()
    
    print(f"\n✅ Generated {len(files)} test curator output files")
    print("\nScenarios created:")
    print("  1. Standard - Typical daily update with mixed content")
    print("  2. Governance - Focus on proposals and voting")
    print("  3. Credits - Ecocredit and marketplace activity")
    print("  4. Community - Community events and engagement")
    print("  5. Minimal - Edge case with only 2 posts")
    
    print("\n📝 Next steps:")
    print("  1. Run the X Bot to process these files:")
    print("     python bots/x_daily_bot.py")
    print("  2. Review generated drafts:")
    print("     python bots/review/cli_reviewer.py list")
    print("  3. Approve/reject drafts:")
    print("     python bots/review/cli_reviewer.py review-all")


if __name__ == "__main__":
    main()