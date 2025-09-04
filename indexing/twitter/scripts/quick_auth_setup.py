#!/usr/bin/env python3
"""
Quick authentication setup with provided cookies
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from utils.auth_manager import TwitterAuthManager

def setup_with_cookies():
    """Set up authentication with the provided cookies"""
    
    # Your cookies
    cookies = """auth_token=994ffb9622fc4a8b17a4b7f1e44c53403354477e; ct0=6d95e2203609cc2990e98c960bb90c4fb066cc7f5b0b9df0f3049d095642a221422ad4f6062b0abcc908f0aafbc09800258701455f11bc43e8c562c05c3fa67c814d638c9e9677f03e68fd102cc7280e; guest_id=v1%3A175460676768999756; kdt=70RceDuHWdmwtXtalBI1JP9bKCUVQzXDQbleNKuD; twid=u%3D1752823506524651520"""
    
    # Use provided username
    print("Setting up Twitter authentication...")
    username = "ReFiChat"
    print(f"Using username: @{username}")
    
    # Initialize auth manager
    auth_manager = TwitterAuthManager()
    
    # Add account with cookies
    success = auth_manager.add_account(
        username=username,
        cookies=cookies
    )
    
    if success:
        print(f"\n✓ Successfully configured authentication for @{username}")
        print("\nYou can now run:")
        print("  python indexing/twitter/scripts/test_twitter_scrape.py")
        print("\nOr directly collect tweets:")
        print("  python indexing/twitter/scripts/index_twitter.py --test")
        return True
    else:
        print(f"\n✗ Failed to configure authentication")
        return False

if __name__ == "__main__":
    setup_with_cookies()