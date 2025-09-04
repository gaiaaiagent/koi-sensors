#!/usr/bin/env python3
"""
Interactive setup script for Twitter authentication
Helps users configure auth for Twitter scraping
"""

import sys
import os
from pathlib import Path
import json
from getpass import getpass
from loguru import logger

# Add parent directories to path
sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent.parent))

from utils.auth_manager import TwitterAuthManager


def print_header():
    """Print script header"""
    print("\n" + "="*60)
    print("Twitter/X Authentication Setup")
    print("="*60)
    print("\nThis script will help you set up authentication for Twitter scraping.")
    print("Your credentials will be encrypted and stored securely.\n")


def print_cookie_instructions():
    """Print instructions for getting cookies"""
    print("\n" + "-"*60)
    print("How to get Twitter cookies:")
    print("-"*60)
    print("""
1. Open Twitter/X (twitter.com or x.com) in your browser
2. Log in to your account
3. Open Developer Tools:
   - Chrome/Edge: Press F12 or Ctrl+Shift+I (Cmd+Option+I on Mac)
   - Firefox: Press F12 or Ctrl+Shift+I (Cmd+Option+I on Mac)
   - Safari: Enable Developer menu in Preferences, then Cmd+Option+I
   
4. Go to the 'Application' tab (Chrome) or 'Storage' tab (Firefox)
5. In the left sidebar, expand 'Cookies' and click on 'https://twitter.com'
6. Find these important cookies:
   - auth_token (40-character string) - REQUIRED
   - ct0 (CSRF token) - REQUIRED
   
7. Copy the entire cookie string or just these key values
8. You can paste them in format: "auth_token=xxx; ct0=yyy"
   Or as JSON: {"auth_token": "xxx", "ct0": "yyy"}
""")


def get_auth_method():
    """Get user's preferred authentication method"""
    print("\nChoose authentication method:")
    print("1. Cookie-based (RECOMMENDED - most reliable)")
    print("2. Auth token only (simpler but less features)")
    print("3. Username/Password (least reliable, not recommended)")
    print("4. Environment variables (.env file)")
    print("5. Exit")
    
    while True:
        choice = input("\nEnter your choice (1-5): ").strip()
        if choice in ['1', '2', '3', '4', '5']:
            return int(choice)
        print("Invalid choice. Please enter 1-5.")


def setup_cookie_auth(auth_manager: TwitterAuthManager):
    """Set up cookie-based authentication"""
    print_cookie_instructions()
    
    username = input("\nEnter Twitter username (without @): ").strip()
    if not username:
        print("Username required!")
        return False
    
    print("\nPaste your cookies (press Enter twice when done):")
    cookie_lines = []
    while True:
        line = input()
        if not line:
            break
        cookie_lines.append(line)
    
    cookies = ' '.join(cookie_lines)
    
    if not cookies:
        print("No cookies provided!")
        return False
    
    # Validate cookies
    if not auth_manager.validate_cookies(cookies):
        print("\nWarning: Cookies might be incomplete. Make sure you have auth_token and ct0.")
        proceed = input("Continue anyway? (y/n): ").lower()
        if proceed != 'y':
            return False
    
    # Optional: Get email for account recovery
    email = input("\nEmail associated with account (optional, press Enter to skip): ").strip()
    
    # Save account
    success = auth_manager.add_account(
        username=username,
        cookies=cookies,
        email=email if email else None
    )
    
    if success:
        print(f"\n✓ Successfully added account @{username}")
        return True
    else:
        print(f"\n✗ Failed to add account @{username}")
        return False


def setup_token_auth(auth_manager: TwitterAuthManager):
    """Set up auth token only"""
    print("\nAuth token setup:")
    print("The auth_token is a 40-character string from your browser cookies.")
    
    username = input("\nEnter Twitter username (without @): ").strip()
    if not username:
        print("Username required!")
        return False
    
    auth_token = getpass("Enter auth_token (hidden for security): ").strip()
    
    if not auth_token or len(auth_token) != 40:
        print("Invalid auth_token! Should be 40 characters.")
        return False
    
    success = auth_manager.add_account(
        username=username,
        auth_token=auth_token
    )
    
    if success:
        print(f"\n✓ Successfully added account @{username}")
        return True
    else:
        print(f"\n✗ Failed to add account @{username}")
        return False


def setup_password_auth(auth_manager: TwitterAuthManager):
    """Set up username/password authentication"""
    print("\nUsername/Password setup:")
    print("⚠️  Warning: This method is less reliable and may trigger security checks.")
    
    username = input("\nEnter Twitter username (without @): ").strip()
    if not username:
        print("Username required!")
        return False
    
    password = getpass("Enter password (hidden): ").strip()
    if not password:
        print("Password required!")
        return False
    
    email = input("Enter email (required for login): ").strip()
    if not email:
        print("Email required!")
        return False
    
    email_password = getpass("Enter email password (optional, press Enter to skip): ").strip()
    
    success = auth_manager.add_account(
        username=username,
        password=password,
        email=email
    )
    
    if success:
        print(f"\n✓ Successfully added account @{username}")
        return True
    else:
        print(f"\n✗ Failed to add account @{username}")
        return False


def setup_env_auth(auth_manager: TwitterAuthManager):
    """Set up authentication from environment variables"""
    print("\nEnvironment variable setup:")
    print("Add the following to your .env file:")
    print("""
TWITTER_AUTH_TOKEN=your_40_char_auth_token
TWITTER_COOKIES='auth_token=xxx; ct0=yyy'
TWITTER_USERNAME=your_username
""")
    
    # Check if .env exists
    env_file = Path(__file__).parent.parent.parent / '.env'
    
    if env_file.exists():
        print(f"\n.env file found at: {env_file}")
        print("Add the variables above to your .env file.")
    else:
        create = input("\nNo .env file found. Create one? (y/n): ").lower()
        if create == 'y':
            template = """# Twitter Authentication
TWITTER_AUTH_TOKEN=
TWITTER_COOKIES=
TWITTER_USERNAME=
"""
            with open(env_file, 'w') as f:
                f.write(template)
            print(f"\n✓ Created .env template at: {env_file}")
            print("Edit this file and add your credentials.")
    
    # Try to load from env
    auth_token = auth_manager.get_auth_token_from_env()
    cookies = auth_manager.get_cookies_from_env()
    username = os.getenv('TWITTER_USERNAME')
    
    if auth_token or cookies:
        if username:
            success = auth_manager.add_account(
                username=username,
                auth_token=auth_token,
                cookies=cookies
            )
            if success:
                print(f"\n✓ Loaded credentials for @{username} from environment")
                return True
        else:
            print("\n⚠️  Found credentials but TWITTER_USERNAME not set")
    else:
        print("\n⚠️  No credentials found in environment variables")
    
    return False


def test_authentication(auth_manager: TwitterAuthManager):
    """Test if authentication is working"""
    print("\n" + "-"*60)
    print("Testing authentication...")
    print("-"*60)
    
    account = auth_manager.get_best_account()
    
    if not account:
        print("✗ No accounts configured")
        return False
    
    print(f"✓ Found account: @{account['username']}")
    
    # Check what auth methods are available
    if 'cookies' in account and account['cookies']:
        print("✓ Cookies configured")
    if 'auth_token' in account and account['auth_token']:
        print("✓ Auth token configured")
    if 'password' in account and account['password']:
        print("✓ Password configured")
    
    print("\nTo test actual Twitter connection, run:")
    print("python /home/regenai/project/indexing/twitter/scripts/test_twitter_scrape.py")
    
    return True


def main():
    """Main setup flow"""
    print_header()
    
    # Initialize auth manager
    auth_manager = TwitterAuthManager()
    
    # Check existing accounts
    existing = auth_manager.load_accounts()
    if existing:
        print(f"\nFound {len(existing)} existing account(s):")
        for acc in existing:
            print(f"  - @{acc['username']}")
        
        overwrite = input("\nAdd another account or update existing? (y/n): ").lower()
        if overwrite != 'y':
            test_authentication(auth_manager)
            return
    
    # Get authentication method
    method = get_auth_method()
    
    success = False
    
    if method == 1:
        success = setup_cookie_auth(auth_manager)
    elif method == 2:
        success = setup_token_auth(auth_manager)
    elif method == 3:
        success = setup_password_auth(auth_manager)
    elif method == 4:
        success = setup_env_auth(auth_manager)
    elif method == 5:
        print("\nExiting...")
        return
    
    if success:
        # Test the authentication
        test_authentication(auth_manager)
        
        # Offer to add more accounts
        add_more = input("\nAdd another account? (y/n): ").lower()
        if add_more == 'y':
            main()  # Recursive call to add more
    else:
        print("\nAuthentication setup failed. Please try again.")
        retry = input("Retry? (y/n): ").lower()
        if retry == 'y':
            main()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nSetup cancelled by user.")
    except Exception as e:
        logger.error(f"Setup failed: {e}")
        print(f"\nError: {e}")
        print("Please check the logs for more details.")