"""
Twitter authentication manager for secure credential storage
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional, List
from loguru import logger
import keyring
from cryptography.fernet import Fernet
from dotenv import load_dotenv


class TwitterAuthManager:
    """
    Manages Twitter authentication credentials securely
    Supports cookies, auth tokens, and account rotation
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        """
        Initialize the auth manager
        
        Args:
            storage_path: Path to store encrypted credentials
        """
        self.storage_path = storage_path or Path(__file__).parent.parent / 'storage' / 'cache'
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.auth_file = self.storage_path / 'twitter_auth.json'
        self.key_file = self.storage_path / '.auth_key'
        
        # Load environment variables
        load_dotenv()
        
        # Initialize encryption
        self.cipher = self._get_or_create_cipher()
        
    def _get_or_create_cipher(self) -> Fernet:
        """
        Get or create encryption key for secure storage
        """
        if self.key_file.exists():
            with open(self.key_file, 'rb') as f:
                key = f.read()
        else:
            key = Fernet.generate_key()
            with open(self.key_file, 'wb') as f:
                f.write(key)
            # Set restrictive permissions
            os.chmod(self.key_file, 0o600)
        
        return Fernet(key)
    
    def add_account(
        self,
        username: str,
        cookies: Optional[str] = None,
        auth_token: Optional[str] = None,
        password: Optional[str] = None,
        email: Optional[str] = None
    ) -> bool:
        """
        Add a Twitter account with authentication details
        
        Args:
            username: Twitter username (without @)
            cookies: Cookie string or JSON
            auth_token: Auth token from browser cookies
            password: Account password (optional, less secure)
            email: Email for account recovery
            
        Returns:
            True if account added successfully
        """
        try:
            # Load existing accounts
            accounts = self.load_accounts()
            
            # Prepare account data
            account_data = {
                'username': username,
                'cookies': cookies,
                'auth_token': auth_token,
                'password': password,
                'email': email
            }
            
            # Remove None values
            account_data = {k: v for k, v in account_data.items() if v is not None}
            
            # Encrypt sensitive data
            if 'cookies' in account_data:
                account_data['cookies'] = self._encrypt(account_data['cookies'])
            if 'auth_token' in account_data:
                account_data['auth_token'] = self._encrypt(account_data['auth_token'])
            if 'password' in account_data:
                account_data['password'] = self._encrypt(account_data['password'])
            
            # Update or add account
            existing = next((a for a in accounts if a['username'] == username), None)
            if existing:
                existing.update(account_data)
                logger.info(f"Updated account: @{username}")
            else:
                accounts.append(account_data)
                logger.info(f"Added new account: @{username}")
            
            # Save accounts
            self.save_accounts(accounts)
            return True
            
        except Exception as e:
            logger.error(f"Failed to add account @{username}: {e}")
            return False
    
    def get_account(self, username: str) -> Optional[Dict]:
        """
        Get decrypted account details
        
        Args:
            username: Twitter username
            
        Returns:
            Account dictionary with decrypted credentials
        """
        accounts = self.load_accounts()
        account = next((a for a in accounts if a['username'] == username), None)
        
        if account:
            # Decrypt sensitive data
            decrypted = account.copy()
            if 'cookies' in decrypted:
                decrypted['cookies'] = self._decrypt(decrypted['cookies'])
            if 'auth_token' in decrypted:
                decrypted['auth_token'] = self._decrypt(decrypted['auth_token'])
            if 'password' in decrypted:
                decrypted['password'] = self._decrypt(decrypted['password'])
            
            return decrypted
        
        return None
    
    def load_accounts(self) -> List[Dict]:
        """
        Load all stored accounts
        
        Returns:
            List of account dictionaries
        """
        if not self.auth_file.exists():
            return []
        
        try:
            with open(self.auth_file, 'r') as f:
                data = json.load(f)
                return data.get('accounts', [])
        except Exception as e:
            logger.error(f"Failed to load accounts: {e}")
            return []
    
    def save_accounts(self, accounts: List[Dict]):
        """
        Save accounts to encrypted storage
        
        Args:
            accounts: List of account dictionaries
        """
        try:
            data = {'accounts': accounts}
            with open(self.auth_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            # Set restrictive permissions
            os.chmod(self.auth_file, 0o600)
            
        except Exception as e:
            logger.error(f"Failed to save accounts: {e}")
    
    def _encrypt(self, data: str) -> str:
        """Encrypt sensitive data"""
        return self.cipher.encrypt(data.encode()).decode()
    
    def _decrypt(self, data: str) -> str:
        """Decrypt sensitive data"""
        return self.cipher.decrypt(data.encode()).decode()
    
    def get_auth_token_from_env(self) -> Optional[str]:
        """
        Get auth token from environment variable
        
        Returns:
            Auth token or None
        """
        return os.getenv('TWITTER_AUTH_TOKEN')
    
    def get_cookies_from_env(self) -> Optional[str]:
        """
        Get cookies from environment variable
        
        Returns:
            Cookie string or None
        """
        return os.getenv('TWITTER_COOKIES')
    
    def validate_cookies(self, cookies: str) -> bool:
        """
        Validate cookie format
        
        Args:
            cookies: Cookie string to validate
            
        Returns:
            True if valid format
        """
        # Check for auth_token in cookies
        if 'auth_token' not in cookies:
            logger.warning("Cookies missing auth_token")
            return False
        
        # Check for ct0 token (CSRF token)
        if 'ct0' not in cookies:
            logger.warning("Cookies missing ct0 token")
            return False
        
        return True
    
    def parse_cookies(self, cookie_string: str) -> Dict[str, str]:
        """
        Parse cookie string to dictionary
        
        Args:
            cookie_string: Cookie string like "key1=val1; key2=val2"
            
        Returns:
            Dictionary of cookies
        """
        cookies = {}
        
        # Handle JSON format
        if cookie_string.startswith('{'):
            try:
                return json.loads(cookie_string)
            except:
                pass
        
        # Parse string format
        for item in cookie_string.split(';'):
            item = item.strip()
            if '=' in item:
                key, value = item.split('=', 1)
                cookies[key.strip()] = value.strip()
        
        return cookies
    
    def format_cookies_for_twscrape(self, cookies: Dict[str, str]) -> str:
        """
        Format cookies for twscrape API
        
        Args:
            cookies: Cookie dictionary
            
        Returns:
            Formatted cookie string
        """
        return '; '.join([f"{k}={v}" for k, v in cookies.items()])
    
    def get_best_account(self) -> Optional[Dict]:
        """
        Get the best available account (with most complete auth)
        
        Returns:
            Account dictionary or None
        """
        accounts = self.load_accounts()
        
        # Prioritize accounts with cookies
        for account in accounts:
            if 'cookies' in account:
                return self.get_account(account['username'])
        
        # Then auth_token
        for account in accounts:
            if 'auth_token' in account:
                return self.get_account(account['username'])
        
        # Finally any account
        if accounts:
            return self.get_account(accounts[0]['username'])
        
        return None