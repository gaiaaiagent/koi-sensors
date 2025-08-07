# Credential Manager - Interactive Setup for Data Sources

## Overview

This system will:
1. Check each data source
2. Ask for credentials if needed
3. Let you skip with a note if you don't have them yet
4. Store credentials securely for reuse
5. Continue indexing what's available

## Credential Manager Implementation

### Main Credential Manager

**File: `indexing/utils/credential_manager.py`**

```python
import os
import json
from pathlib import Path
from typing import Dict, Optional, Any
from getpass import getpass
import keyring
from cryptography.fernet import Fernet
from loguru import logger

class CredentialManager:
    """
    Manage credentials for various data sources
    Stores credentials securely and tracks what's available
    """
    
    def __init__(self, config_dir: Path = None):
        self.config_dir = config_dir or Path("/home/regenai/project/indexing/config")
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Credential status file (what's configured, what's pending)
        self.status_file = self.config_dir / "credential_status.json"
        self.env_file = self.config_dir / ".env"
        
        # Load existing status
        self.status = self._load_status()
        
        # Use system keyring for sensitive data (optional)
        self.use_keyring = self._check_keyring_available()
        
    def _load_status(self) -> Dict:
        """Load credential status"""
        if self.status_file.exists():
            with open(self.status_file) as f:
                return json.load(f)
        return {
            'configured': {},
            'pending': {},
            'notes': {}
        }
    
    def _save_status(self):
        """Save credential status"""
        with open(self.status_file, 'w') as f:
            json.dump(self.status, f, indent=2)
    
    def _check_keyring_available(self) -> bool:
        """Check if system keyring is available"""
        try:
            keyring.get_password("test", "test")
            return True
        except:
            return False
    
    def get_credential(self, service: str, key: str, required: bool = False) -> Optional[str]:
        """
        Get a credential, returning None if not available
        """
        # Check environment variable first
        env_key = f"{service.upper()}_{key.upper()}"
        value = os.getenv(env_key)
        
        if value:
            return value
        
        # Check keyring if available
        if self.use_keyring:
            value = keyring.get_password(service, key)
            if value:
                return value
        
        # Check .env file
        if self.env_file.exists():
            with open(self.env_file) as f:
                for line in f:
                    if line.startswith(f"{env_key}="):
                        return line.split('=', 1)[1].strip()
        
        return None
    
    def set_credential(self, service: str, key: str, value: str):
        """Store a credential"""
        env_key = f"{service.upper()}_{key.upper()}"
        
        # Store in .env file
        env_lines = []
        if self.env_file.exists():
            with open(self.env_file) as f:
                env_lines = f.readlines()
        
        # Update or add the credential
        found = False
        for i, line in enumerate(env_lines):
            if line.startswith(f"{env_key}="):
                env_lines[i] = f"{env_key}={value}\n"
                found = True
                break
        
        if not found:
            env_lines.append(f"{env_key}={value}\n")
        
        # Write back
        with open(self.env_file, 'w') as f:
            f.writelines(env_lines)
        
        # Also set in environment for current session
        os.environ[env_key] = value
        
        # Update status
        if service not in self.status['configured']:
            self.status['configured'][service] = {}
        self.status['configured'][service][key] = True
        
        # Remove from pending if it was there
        if service in self.status['pending']:
            self.status['pending'][service].pop(key, None)
            if not self.status['pending'][service]:
                del self.status['pending'][service]
        
        self._save_status()
    
    def set_pending(self, service: str, key: str, note: str):
        """Mark a credential as pending with a note"""
        if service not in self.status['pending']:
            self.status['pending'][service] = {}
        self.status['pending'][service][key] = True
        
        if service not in self.status['notes']:
            self.status['notes'][service] = {}
        self.status['notes'][service][key] = note
        
        self._save_status()
    
    def is_configured(self, service: str, key: str) -> bool:
        """Check if a credential is configured"""
        return bool(self.get_credential(service, key))
    
    def get_status_report(self) -> Dict:
        """Get a report of credential status"""
        report = {
            'configured': [],
            'pending': [],
            'notes': {}
        }
        
        for service, keys in self.status.get('configured', {}).items():
            for key in keys:
                report['configured'].append(f"{service}.{key}")
        
        for service, keys in self.status.get('pending', {}).items():
            for key in keys:
                report['pending'].append(f"{service}.{key}")
                note = self.status.get('notes', {}).get(service, {}).get(key)
                if note:
                    report['notes'][f"{service}.{key}"] = note
        
        return report
```

### Interactive Setup Script

**File: `indexing/scripts/setup_credentials.py`**

```python
#!/usr/bin/env python3
"""
Interactive setup for data source credentials
"""

import sys
from pathlib import Path
import yaml
from typing import Dict, List, Tuple
import httpx
from getpass import getpass

sys.path.append(str(Path(__file__).parent.parent))

from utils.credential_manager import CredentialManager
from loguru import logger

class InteractiveSetup:
    """
    Interactive setup wizard for credentials
    """
    
    def __init__(self):
        self.cred_manager = CredentialManager()
        self.config_path = Path(__file__).parent.parent / "config" / "sources.yaml"
        
    def run(self):
        """Run interactive setup"""
        print("\n" + "="*60)
        print("🔐 REGEN NETWORK INDEXING - CREDENTIAL SETUP")
        print("="*60)
        print("\nThis wizard will help you configure access to data sources.")
        print("You can skip any source and add credentials later.\n")
        
        # Load config
        with open(self.config_path) as f:
            config = yaml.safe_load(f)
        
        # Check each source type
        self.setup_discourse(config)
        self.setup_discord(config)
        self.setup_twitter(config)
        self.setup_notion(config)
        
        # Show summary
        self.show_summary()
        
        print("\n✅ Setup complete!")
        print("\nYour credentials are stored in:")
        print(f"  - {self.cred_manager.env_file}")
        print(f"  - Status: {self.cred_manager.status_file}")
        print("\n⚠️  Remember to add .env to .gitignore!")
    
    def setup_discourse(self, config: Dict):
        """Setup Discourse forum credentials"""
        forums = config.get('sources', {}).get('discourse', [])
        
        if not forums:
            return
        
        print("\n" + "-"*40)
        print("💬 DISCOURSE FORUMS")
        print("-"*40)
        print("API keys provide higher rate limits but are OPTIONAL.")
        print("The system will work without them (slower).\n")
        
        for forum in forums:
            name = forum['name']
            url = forum['url']
            
            # Check if already configured
            if self.cred_manager.is_configured('discourse', name):
                print(f"✅ {name}: Already configured")
                continue
            
            print(f"\n📍 {name} ({url})")
            print("Options:")
            print("  1) Enter API key")
            print("  2) Skip (use anonymous access)")
            print("  3) Add note (don't have key yet)")
            
            choice = input("Choice [1/2/3]: ").strip()
            
            if choice == '1':
                api_key = getpass(f"API key for {name}: ").strip()
                if api_key:
                    # Test the API key
                    if self.test_discourse_key(url, api_key):
                        self.cred_manager.set_credential('discourse', name, api_key)
                        print("✅ API key verified and saved!")
                    else:
                        print("⚠️  API key didn't work, saving anyway...")
                        self.cred_manager.set_credential('discourse', name, api_key)
            
            elif choice == '3':
                note = input("Note (e.g., 'waiting for admin approval'): ").strip()
                self.cred_manager.set_pending('discourse', name, note or "Pending")
                print(f"📝 Noted: {note}")
            
            else:
                print("⏭️  Skipping (will use anonymous access)")
    
    def setup_discord(self, config: Dict):
        """Setup Discord bot credentials"""
        discord = config.get('sources', {}).get('discord', {})
        
        if not discord or not discord.get('enabled'):
            return
        
        print("\n" + "-"*40)
        print("🤖 DISCORD BOT")
        print("-"*40)
        print("Discord requires a bot token to read message history.\n")
        
        if self.cred_manager.is_configured('discord', 'bot_token'):
            print("✅ Bot token already configured")
            return
        
        print("Options:")
        print("  1) Enter bot token")
        print("  2) Skip for now")
        print("  3) Add note")
        
        choice = input("Choice [1/2/3]: ").strip()
        
        if choice == '1':
            bot_token = getpass("Discord bot token: ").strip()
            if bot_token:
                self.cred_manager.set_credential('discord', 'bot_token', bot_token)
                
                guild_id = input("Discord server (guild) ID: ").strip()
                if guild_id:
                    self.cred_manager.set_credential('discord', 'guild_id', guild_id)
                
                print("✅ Discord credentials saved!")
        
        elif choice == '3':
            note = input("Note (e.g., 'need to create bot first'): ").strip()
            self.cred_manager.set_pending('discord', 'bot_token', note or "Pending")
            print(f"📝 Noted: {note}")
        
        else:
            print("⏭️  Skipping Discord setup")
    
    def setup_twitter(self, config: Dict):
        """Setup Twitter/X access strategy"""
        twitter = config.get('sources', {}).get('twitter', {})
        
        if not twitter or not twitter.get('enabled'):
            return
        
        print("\n" + "-"*40)
        print("🐦 TWITTER/X")
        print("-"*40)
        print("Choose your Twitter data access strategy:\n")
        
        print("Options:")
        print("  1) I have exported my Twitter archive")
        print("  2) Use API (requires API key)")
        print("  3) Scrape public timeline (no credentials)")
        print("  4) Skip for now")
        print("  5) Add note")
        
        choice = input("Choice [1/2/3/4/5]: ").strip()
        
        if choice == '1':
            archive_path = input("Path to Twitter archive ZIP: ").strip()
            if archive_path and Path(archive_path).exists():
                self.cred_manager.set_credential('twitter', 'archive_path', archive_path)
                self.cred_manager.set_credential('twitter', 'strategy', 'archive')
                print("✅ Twitter archive path saved!")
            else:
                print("⚠️  Archive file not found")
        
        elif choice == '2':
            api_key = getpass("Twitter API key: ").strip()
            if api_key:
                self.cred_manager.set_credential('twitter', 'api_key', api_key)
                self.cred_manager.set_credential('twitter', 'strategy', 'api')
                print("✅ Twitter API key saved!")
        
        elif choice == '3':
            self.cred_manager.set_credential('twitter', 'strategy', 'scrape')
            print("✅ Will use public scraping (no credentials needed)")
        
        elif choice == '5':
            note = input("Note (e.g., 'waiting for API approval'): ").strip()
            self.cred_manager.set_pending('twitter', 'access', note or "Pending")
            print(f"📝 Noted: {note}")
        
        else:
            print("⏭️  Skipping Twitter setup")
    
    def setup_notion(self, config: Dict):
        """Setup Notion API access"""
        notion = config.get('sources', {}).get('notion', {})
        
        if not notion or not notion.get('enabled'):
            return
        
        print("\n" + "-"*40)
        print("📓 NOTION")
        print("-"*40)
        print("Notion requires API access to read the KOI database.\n")
        
        if self.cred_manager.is_configured('notion', 'api_key'):
            print("✅ Notion API already configured")
            return
        
        print("Options:")
        print("  1) Enter Notion API key")
        print("  2) Skip for now")
        print("  3) Add note")
        
        choice = input("Choice [1/2/3]: ").strip()
        
        if choice == '1':
            api_key = getpass("Notion API key: ").strip()
            if api_key:
                self.cred_manager.set_credential('notion', 'api_key', api_key)
                
                database_id = input("Notion database ID: ").strip()
                if database_id:
                    self.cred_manager.set_credential('notion', 'database_id', database_id)
                
                print("✅ Notion credentials saved!")
        
        elif choice == '3':
            note = input("Note (e.g., 'need access from RND team'): ").strip()
            self.cred_manager.set_pending('notion', 'api_key', note or "Pending")
            print(f"📝 Noted: {note}")
        
        else:
            print("⏭️  Skipping Notion setup")
    
    def test_discourse_key(self, url: str, api_key: str) -> bool:
        """Test if Discourse API key works"""
        try:
            response = httpx.get(
                f"{url}/categories.json",
                headers={
                    'Api-Key': api_key,
                    'Api-Username': 'system'
                },
                timeout=5
            )
            return response.status_code == 200
        except:
            return False
    
    def show_summary(self):
        """Show credential status summary"""
        report = self.cred_manager.get_status_report()
        
        print("\n" + "="*60)
        print("📊 CREDENTIAL STATUS SUMMARY")
        print("="*60)
        
        if report['configured']:
            print("\n✅ Configured:")
            for item in report['configured']:
                print(f"  - {item}")
        
        if report['pending']:
            print("\n⏳ Pending:")
            for item in report['pending']:
                note = report['notes'].get(item, '')
                if note:
                    print(f"  - {item}: {note}")
                else:
                    print(f"  - {item}")
        
        # Check what sources are ready
        print("\n🚀 Ready to index:")
        ready = []
        
        # Always ready (no auth needed)
        ready.extend(['GitHub', 'GitLab', 'Websites', 'Medium'])
        
        # Conditionally ready
        if report['configured']:
            for item in report['configured']:
                if 'discourse' in item:
                    ready.append('Discourse (enhanced)')
                elif 'discord' in item:
                    ready.append('Discord')
                elif 'twitter' in item:
                    ready.append('Twitter')
                elif 'notion' in item:
                    ready.append('Notion')
        
        # Discourse works without auth too
        if 'Discourse (enhanced)' not in ready:
            ready.append('Discourse (anonymous)')
        
        for source in ready:
            print(f"  ✓ {source}")

if __name__ == "__main__":
    setup = InteractiveSetup()
    setup.run()
```

### Updated Collection Script with Credential Handling

**File: `indexing/collectors/discourse_collector.py` (updated section)**

```python
from utils.credential_manager import CredentialManager

class DiscourseCollector(BaseCollector):
    def __init__(self):
        super().__init__()
        self.cred_manager = CredentialManager()
        
    async def collect(self, config: Dict) -> List[Dict]:
        """Collect with optional authentication"""
        
        forum_name = config['name']
        forum_url = config['url']
        
        # Check for API key (optional)
        api_key = self.cred_manager.get_credential('discourse', forum_name)
        
        headers = {}
        if api_key:
            headers['Api-Key'] = api_key
            headers['Api-Username'] = 'system'
            logger.info(f"Using API key for {forum_name} (higher rate limits)")
        else:
            logger.info(f"No API key for {forum_name} (using anonymous access)")
        
        # Continue with collection...
```

### Check Credentials Script

**File: `indexing/scripts/check_credentials.py`**

```python
#!/usr/bin/env python3
"""
Check credential status and what sources are accessible
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from utils.credential_manager import CredentialManager

def main():
    cred_manager = CredentialManager()
    report = cred_manager.get_status_report()
    
    print("\n🔐 Credential Status")
    print("="*40)
    
    # Load .env file path
    env_file = cred_manager.env_file
    if env_file.exists():
        print(f"✅ Credentials file: {env_file}")
        print(f"   Size: {env_file.stat().st_size} bytes")
    else:
        print("⚠️  No credentials file yet")
        print(f"   Will be created at: {env_file}")
    
    print("\nConfigured credentials:")
    if report['configured']:
        for item in sorted(report['configured']):
            print(f"  ✅ {item}")
    else:
        print("  None yet")
    
    print("\nPending credentials:")
    if report['pending']:
        for item in sorted(report['pending']):
            note = report['notes'].get(item, '')
            print(f"  ⏳ {item}: {note}")
    else:
        print("  None")
    
    print("\n💡 To add credentials, run:")
    print("   python indexing/scripts/setup_credentials.py")

if __name__ == "__main__":
    main()
```

## Usage Flow

1. **First Time Setup:**
```bash
# Run interactive setup
python indexing/scripts/setup_credentials.py

# It will ask for each credential type:
# - Discourse API keys (optional, skip if you don't have)
# - Discord bot token (skip if not ready)
# - Twitter strategy (archive/API/scrape)
# - Notion API (skip if no access yet)
```

2. **Check What's Configured:**
```bash
python indexing/scripts/check_credentials.py
```

3. **The system continues with available sources:**
```bash
# Test collection will automatically use configured credentials
# and skip sources that need missing credentials
python indexing/scripts/test_collection.py
```

## Features

✅ **Interactive prompts** for each credential type
✅ **Optional credentials** - can skip and continue
✅ **Notes for pending items** - track what you're waiting for
✅ **Secure storage** in .env file
✅ **Reusable** - credentials persist between runs
✅ **Status tracking** - know what's configured vs pending
✅ **Graceful degradation** - works with what's available

## Example Session

```
🔐 REGEN NETWORK INDEXING - CREDENTIAL SETUP
============================================================

💬 DISCOURSE FORUMS
----------------------------------------
API keys provide higher rate limits but are OPTIONAL.

📍 regen-forum (https://forum.regen.network)
Options:
  1) Enter API key
  2) Skip (use anonymous access)
  3) Add note (don't have key yet)
Choice [1/2/3]: 3
Note: Waiting for admin to generate key
📝 Noted: Waiting for admin to generate key

🤖 DISCORD BOT
----------------------------------------
Options:
  1) Enter bot token
  2) Skip for now
  3) Add note
Choice [1/2/3]: 3
Note: Need to create bot first
📝 Noted: Need to create bot first

📊 CREDENTIAL STATUS SUMMARY
============================================================
⏳ Pending:
  - discourse.regen-forum: Waiting for admin to generate key
  - discord.bot_token: Need to create bot first

🚀 Ready to index:
  ✓ GitHub
  ✓ GitLab
  ✓ Websites
  ✓ Medium
  ✓ Discourse (anonymous)
```

The system will work with whatever credentials you have and continue indexing the accessible sources!