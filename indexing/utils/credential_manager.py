"""
Credential manager for secure API key storage and retrieval
Based on CREDENTIAL_SETUP.md requirements
"""

import os
import json
from pathlib import Path
from typing import Dict, Optional, Any
from cryptography.fernet import Fernet
import keyring
from dotenv import load_dotenv, set_key
from loguru import logger


class CredentialManager:
    """
    Manages credentials for various data sources
    Supports .env files and system keyring
    """
    
    def __init__(self, env_path: Optional[Path] = None):
        """
        Initialize credential manager
        
        Args:
            env_path: Path to .env file (defaults to project root)
        """
        self.env_path = env_path or Path("/home/regenai/project/.env")
        self.keyring_service = "regen_indexing"
        self.credentials_cache = {}
        
        # Load environment variables
        if self.env_path.exists():
            load_dotenv(self.env_path)
            logger.info(f"Loaded credentials from {self.env_path}")
        else:
            logger.warning(f"No .env file found at {self.env_path}")
        
        # Initialize encryption (optional)
        self.cipher = None
        self._init_encryption()
    
    def _init_encryption(self):
        """
        Initialize encryption for sensitive data
        """
        key_file = self.env_path.parent / ".encryption_key"
        
        try:
            if key_file.exists():
                key = key_file.read_bytes()
            else:
                # Generate new encryption key
                key = Fernet.generate_key()
                key_file.write_bytes(key)
                key_file.chmod(0o600)  # Restrict permissions
                logger.info("Generated new encryption key")
            
            self.cipher = Fernet(key)
        except Exception as e:
            logger.warning(f"Encryption not available: {e}")
            self.cipher = None
    
    def get(self, key: str, source: Optional[str] = None) -> Optional[str]:
        """
        Get credential value
        
        Args:
            key: Credential key (e.g., 'DISCOURSE_API_KEY_REGEN')
            source: Optional source hint for better error messages
            
        Returns:
            Credential value or None if not found
        """
        # Check cache first
        if key in self.credentials_cache:
            return self.credentials_cache[key]
        
        # Try environment variable
        value = os.getenv(key)
        if value:
            self.credentials_cache[key] = value
            return value
        
        # Try system keyring
        try:
            value = keyring.get_password(self.keyring_service, key)
            if value:
                self.credentials_cache[key] = value
                logger.debug(f"Retrieved {key} from keyring")
                return value
        except Exception as e:
            logger.debug(f"Keyring not available: {e}")
        
        # Log missing credential (but continue anyway)
        if source:
            logger.debug(f"No credential found for {key} (needed for {source})")
        
        return None
    
    def set(self, key: str, value: str, use_keyring: bool = False) -> bool:
        """
        Set credential value
        
        Args:
            key: Credential key
            value: Credential value
            use_keyring: Store in system keyring instead of .env
            
        Returns:
            True if successful
        """
        try:
            if use_keyring:
                # Store in system keyring
                keyring.set_password(self.keyring_service, key, value)
                logger.info(f"Stored {key} in system keyring")
            else:
                # Store in .env file
                set_key(str(self.env_path), key, value)
                logger.info(f"Stored {key} in {self.env_path}")
            
            # Update cache
            self.credentials_cache[key] = value
            return True
            
        except Exception as e:
            logger.error(f"Failed to store credential {key}: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """
        Delete credential
        
        Args:
            key: Credential key to delete
            
        Returns:
            True if successful
        """
        try:
            # Remove from cache
            self.credentials_cache.pop(key, None)
            
            # Try to delete from keyring
            try:
                keyring.delete_password(self.keyring_service, key)
                logger.info(f"Deleted {key} from keyring")
            except:
                pass
            
            # Remove from .env file
            if self.env_path.exists():
                lines = []
                with open(self.env_path, 'r') as f:
                    for line in f:
                        if not line.startswith(f"{key}="):
                            lines.append(line)
                
                with open(self.env_path, 'w') as f:
                    f.writelines(lines)
                
                logger.info(f"Deleted {key} from {self.env_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete credential {key}: {e}")
            return False
    
    def list_credentials(self) -> Dict[str, bool]:
        """
        List all available credentials
        
        Returns:
            Dictionary of credential keys and their availability
        """
        expected_keys = [
            'DISCOURSE_API_KEY_REGEN',
            'DISCOURSE_API_KEY_COMMONS',
            'DISCORD_GUILD_ID',
            'DISCORD_BOT_TOKEN',
            'TWITTER_API_KEY',
            'TWITTER_ARCHIVE_PATH',
            'NOTION_API_KEY',
            'NOTION_DATABASE_ID',
            'MCP_SERVER_URL'
        ]
        
        status = {}
        for key in expected_keys:
            status[key] = self.get(key) is not None
        
        return status
    
    def encrypt_value(self, value: str) -> Optional[str]:
        """
        Encrypt a value
        
        Args:
            value: Value to encrypt
            
        Returns:
            Encrypted value or None if encryption not available
        """
        if not self.cipher:
            return None
        
        try:
            encrypted = self.cipher.encrypt(value.encode())
            return encrypted.decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            return None
    
    def decrypt_value(self, encrypted_value: str) -> Optional[str]:
        """
        Decrypt a value
        
        Args:
            encrypted_value: Encrypted value
            
        Returns:
            Decrypted value or None if decryption fails
        """
        if not self.cipher:
            return None
        
        try:
            decrypted = self.cipher.decrypt(encrypted_value.encode())
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            return None
    
    def validate_discourse_key(self, api_key: str, forum_url: str) -> bool:
        """
        Validate a Discourse API key
        
        Args:
            api_key: API key to validate
            forum_url: Forum URL
            
        Returns:
            True if valid
        """
        import httpx
        
        try:
            headers = {'Api-Key': api_key, 'Api-Username': 'system'}
            response = httpx.get(f"{forum_url}/categories.json", headers=headers)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Failed to validate Discourse key: {e}")
            return False
    
    def validate_discord_token(self, token: str) -> bool:
        """
        Validate a Discord bot token
        
        Args:
            token: Bot token to validate
            
        Returns:
            True if valid
        """
        import httpx
        
        try:
            headers = {'Authorization': f'Bot {token}'}
            response = httpx.get('https://discord.com/api/v10/users/@me', headers=headers)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Failed to validate Discord token: {e}")
            return False
    
    def create_env_template(self) -> Path:
        """
        Create .env.template file with all expected keys
        
        Returns:
            Path to template file
        """
        template_path = self.env_path.parent / ".env.template"
        
        template_content = """# Regen Network Indexing System - Credentials
# Copy this file to .env and fill in your API keys

# Discourse Forums (optional - works without for public content)
DISCOURSE_API_KEY_REGEN=
DISCOURSE_API_KEY_COMMONS=

# Discord Bot (optional - requires bot setup)
DISCORD_GUILD_ID=
DISCORD_BOT_TOKEN=

# Twitter/X API (optional)
TWITTER_API_KEY=
TWITTER_ARCHIVE_PATH=

# Notion API (optional)
NOTION_API_KEY=
NOTION_DATABASE_ID=

# MCP Server (required for live blockchain data)
MCP_SERVER_URL=http://localhost:3000

# Additional configurations
LOG_LEVEL=INFO
CACHE_DIR=/home/regenai/project/indexing/cache
STORAGE_DIR=/home/regenai/project/indexing/storage
"""
        
        template_path.write_text(template_content)
        logger.info(f"Created credential template at {template_path}")
        return template_path


# Singleton instance
_credential_manager = None


def get_credential_manager() -> CredentialManager:
    """
    Get singleton credential manager instance
    
    Returns:
        CredentialManager instance
    """
    global _credential_manager
    if _credential_manager is None:
        _credential_manager = CredentialManager()
    return _credential_manager