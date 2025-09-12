"""
Link Validator - Validates URLs in thread posts
"""

import asyncio
import re
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse
import httpx
from loguru import logger


class LinkValidator:
    """
    Validates links in Twitter threads to ensure they're accessible
    Part of safety guardrails for Milestone B
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize with configuration"""
        self.config = config.get('x_bot', {}).get('validation', {})
        self.check_links = self.config.get('check_links', True)
        self.timeout = self.config.get('timeout_seconds', 10)
        self.max_retries = self.config.get('max_retries', 3)
        
        # Trusted domains (always valid)
        self.trusted_domains = [
            'regen.network',
            'registry.regen.network',
            'docs.regen.network',
            'forum.regen.network',
            'github.com/regen-network',
            'medium.com/regen-network'
        ]
        
        # Headers for HTTP requests
        self.headers = {
            'User-Agent': 'RegenNetwork-XBot/1.0 (Link Validator)'
        }
    
    async def validate_thread(self, thread: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate all links in a thread
        
        Args:
            thread: Thread data with posts
            
        Returns:
            Validation results with link statuses
        """
        if not self.check_links:
            logger.info("Link validation disabled in config")
            return {
                'validated': False,
                'message': 'Link validation disabled'
            }
        
        all_urls = []
        for post in thread.get('posts', []):
            urls = post.get('urls', [])
            all_urls.extend(urls)
        
        # Remove duplicates
        unique_urls = list(set(all_urls))
        
        logger.info(f"Validating {len(unique_urls)} unique URLs")
        
        # Validate each URL
        validation_results = await self._validate_urls(unique_urls)
        
        # Summary
        valid_count = sum(1 for r in validation_results.values() if r['valid'])
        invalid_urls = [url for url, r in validation_results.items() if not r['valid']]
        
        return {
            'validated': True,
            'total_links': len(unique_urls),
            'valid_links': valid_count,
            'invalid_links': len(unique_urls) - valid_count,
            'invalid_urls': invalid_urls,
            'details': validation_results
        }
    
    async def _validate_urls(self, urls: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Validate multiple URLs concurrently
        
        Args:
            urls: List of URLs to validate
            
        Returns:
            Dictionary mapping URLs to validation results
        """
        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=True
        ) as client:
            tasks = [self._validate_single_url(client, url) for url in urls]
            results = await asyncio.gather(*tasks)
        
        return dict(zip(urls, results))
    
    async def _validate_single_url(self, client: httpx.AsyncClient, url: str) -> Dict[str, Any]:
        """
        Validate a single URL
        
        Args:
            client: HTTP client
            url: URL to validate
            
        Returns:
            Validation result for the URL
        """
        # Check if URL is from trusted domain
        if self._is_trusted_domain(url):
            return {
                'valid': True,
                'status_code': 200,
                'reason': 'Trusted domain',
                'checked': False
            }
        
        # Validate URL format
        if not self._is_valid_url_format(url):
            return {
                'valid': False,
                'status_code': None,
                'reason': 'Invalid URL format',
                'error': 'Malformed URL'
            }
        
        # Try to access the URL
        for attempt in range(self.max_retries):
            try:
                # Use HEAD request to avoid downloading full content
                response = await client.head(url, timeout=self.timeout)
                
                # Check status code
                if response.status_code < 400:
                    return {
                        'valid': True,
                        'status_code': response.status_code,
                        'reason': 'URL accessible',
                        'redirect': str(response.url) if str(response.url) != url else None
                    }
                elif response.status_code == 404:
                    return {
                        'valid': False,
                        'status_code': 404,
                        'reason': 'Page not found',
                        'error': 'HTTP 404'
                    }
                elif response.status_code >= 500:
                    # Server error, might be temporary
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(2 ** attempt)  # Exponential backoff
                        continue
                    return {
                        'valid': False,
                        'status_code': response.status_code,
                        'reason': 'Server error',
                        'error': f'HTTP {response.status_code}'
                    }
                else:
                    return {
                        'valid': False,
                        'status_code': response.status_code,
                        'reason': 'Access denied or client error',
                        'error': f'HTTP {response.status_code}'
                    }
                    
            except httpx.TimeoutException:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return {
                    'valid': False,
                    'status_code': None,
                    'reason': 'Timeout',
                    'error': 'Request timed out'
                }
            except httpx.RequestError as e:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return {
                    'valid': False,
                    'status_code': None,
                    'reason': 'Request failed',
                    'error': str(e)
                }
            except Exception as e:
                logger.error(f"Unexpected error validating {url}: {e}")
                return {
                    'valid': False,
                    'status_code': None,
                    'reason': 'Unexpected error',
                    'error': str(e)
                }
        
        # Should not reach here
        return {
            'valid': False,
            'status_code': None,
            'reason': 'Max retries exceeded',
            'error': 'Failed after retries'
        }
    
    def _is_trusted_domain(self, url: str) -> bool:
        """Check if URL is from a trusted domain"""
        for domain in self.trusted_domains:
            if domain in url:
                return True
        return False
    
    def _is_valid_url_format(self, url: str) -> bool:
        """Check if URL has valid format"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False