"""
Thread Composer - Converts Daily Curator output to Twitter thread format
"""

import re
from typing import Dict, Any, List, Optional
from datetime import datetime
from loguru import logger


class ThreadComposer:
    """
    Composes Twitter threads from Daily Curator JSON output
    Follows Milestone B requirements: 3-5 posts with headline, stat, links, CTA
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize with configuration"""
        self.config = config.get('x_bot', {})
        self.style_config = self.config.get('style_guide', {})
        self.max_length = self.style_config.get('max_tweet_length', 280)
        self.use_thread_numbers = self.style_config.get('use_thread_numbers', True)
        self.default_cta = self.style_config.get('default_cta', 'Learn more at regen.network')
        self.hashtags = self.config.get('hashtags', ['#RegenNetwork', '#ReFi'])
        
        # Emoji mapping from style guide
        self.emoji_map = config.get('style_guide', {}).get('emoji_map', {
            'headline': '🌱',
            'stats': '📊',
            'governance': '🗳️',
            'credits': '🌿',
            'community': '💚',
            'link': '🔗',
            'announcement': '📢'
        })
    
    def compose_thread(self, curator_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compose a Twitter thread from curator data
        
        Args:
            curator_data: Output from Daily Curator
            
        Returns:
            Structured thread ready for posting
        """
        posts = curator_data.get('posts', [])
        metadata = curator_data.get('metadata', {})
        
        # Build thread posts
        thread_posts = []
        
        # Process each post from curator
        for i, post in enumerate(posts):
            tweet = self._compose_tweet(post, i, len(posts))
            thread_posts.append(tweet)
        
        # Ensure we have 3-5 posts (Milestone B requirement)
        if len(thread_posts) < 3:
            # Add filler posts if needed
            thread_posts.extend(self._generate_filler_posts(3 - len(thread_posts), metadata))
        elif len(thread_posts) > 5:
            # Trim to 5 posts max
            thread_posts = thread_posts[:5]
        
        # Add thread numbers if configured
        if self.use_thread_numbers:
            thread_posts = self._add_thread_numbers(thread_posts)
        
        # Add hashtags to last post
        thread_posts[-1] = self._add_hashtags(thread_posts[-1])
        
        return {
            'thread_date': curator_data.get('thread_date', datetime.utcnow().isoformat()),
            'posts': thread_posts,
            'metadata': metadata,
            'source': 'daily_curator'
        }
    
    def _compose_tweet(self, post: Dict[str, Any], index: int, total: int) -> Dict[str, Any]:
        """
        Compose a single tweet from post data
        
        Args:
            post: Post data from curator
            index: Post index in thread
            total: Total number of posts
            
        Returns:
            Formatted tweet with metadata
        """
        post_type = post.get('type', 'content')
        content = post.get('content', '')
        
        # Apply emoji based on post type
        if post_type in self.emoji_map:
            emoji = self.emoji_map[post_type]
        elif post_type == 'stat':
            emoji = self.emoji_map.get('stats', '📊')
        else:
            emoji = self.emoji_map.get('link', '🔗')
        
        # Format content based on type
        if post_type == 'headline':
            # Main headline post
            tweet_content = f"{emoji} {content}"
            if not content.endswith('Update'):
                tweet_content = f"{emoji} Regen Network Daily Update"
        elif post_type == 'stat':
            # Statistics post
            tweet_content = f"{emoji} Today's Network Stats:\n{content}"
        elif post_type == 'link':
            # Link post with description
            url = post.get('url', '')
            tweet_content = f"{emoji} {content}"
            if url and len(tweet_content) + len(url) + 2 < self.max_length:
                tweet_content = f"{tweet_content}\n{url}"
        elif post_type == 'cta':
            # Call to action
            tweet_content = content or self.default_cta
            if not tweet_content.startswith('🔗'):
                tweet_content = f"🔗 {tweet_content}"
        else:
            # Generic content
            tweet_content = content
        
        # Extract URLs from content
        urls = self._extract_urls(tweet_content)
        
        # Truncate if too long
        tweet_content = self._truncate_content(tweet_content, self.max_length)
        
        return {
            'type': post_type,
            'content': tweet_content,
            'char_count': len(tweet_content),
            'urls': urls,
            'metadata': post.get('metadata', {}),
            'position': index + 1
        }
    
    def _add_thread_numbers(self, posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Add thread numbers (1/5, 2/5, etc.) to posts"""
        total = len(posts)
        for i, post in enumerate(posts):
            number_prefix = f"{i+1}/{total} "
            remaining_space = self.max_length - len(number_prefix)
            
            # Adjust content to fit with thread number
            if len(post['content']) + len(number_prefix) > self.max_length:
                post['content'] = self._truncate_content(post['content'], remaining_space)
            
            post['content'] = number_prefix + post['content']
            post['char_count'] = len(post['content'])
        
        return posts
    
    def _add_hashtags(self, post: Dict[str, Any]) -> Dict[str, Any]:
        """Add hashtags to a post (usually the last one)"""
        hashtag_text = " ".join(self.hashtags)
        
        # Check if we have room for hashtags
        if len(post['content']) + len(hashtag_text) + 2 <= self.max_length:
            post['content'] = f"{post['content']}\n\n{hashtag_text}"
        elif len(post['content']) + len(hashtag_text) + 1 <= self.max_length:
            post['content'] = f"{post['content']} {hashtag_text}"
        else:
            # Try with just primary hashtag
            if self.hashtags and len(post['content']) + len(self.hashtags[0]) + 1 <= self.max_length:
                post['content'] = f"{post['content']} {self.hashtags[0]}"
        
        post['char_count'] = len(post['content'])
        return post
    
    def _generate_filler_posts(self, count: int, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate filler posts if we have fewer than 3 posts"""
        filler_posts = []
        
        # Standard filler content
        fillers = [
            {
                'type': 'community',
                'content': f"{self.emoji_map.get('community', '💚')} Join our community to stay updated on regenerative finance initiatives"
            },
            {
                'type': 'link',
                'content': f"{self.emoji_map.get('link', '🔗')} Explore our ecosystem at regen.network"
            },
            {
                'type': 'cta',
                'content': self.default_cta
            }
        ]
        
        for i in range(min(count, len(fillers))):
            post = fillers[i]
            filler_posts.append({
                'type': post['type'],
                'content': post['content'],
                'char_count': len(post['content']),
                'urls': self._extract_urls(post['content']),
                'metadata': {'generated': True}
            })
        
        return filler_posts
    
    def _extract_urls(self, content: str) -> List[str]:
        """Extract URLs from content"""
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+(?:[.,;:!?](?=\s|$))?'
        urls = re.findall(url_pattern, content)
        return urls
    
    def _truncate_content(self, content: str, max_length: int) -> str:
        """Truncate content to fit within character limit"""
        if len(content) <= max_length:
            return content
        
        # Try to truncate at a word boundary
        truncated = content[:max_length-3]
        last_space = truncated.rfind(' ')
        if last_space > max_length - 20:  # If we found a space reasonably close to the end
            truncated = truncated[:last_space]
        
        return truncated + "..."