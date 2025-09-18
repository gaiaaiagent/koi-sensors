"""
Site-specific handler for forum.regen.network and other Discourse forums
"""

from datetime import datetime
from typing import Optional, Tuple, Dict, Any, List
from bs4 import BeautifulSoup
import re
from .base_site import BaseSite


class ForumRegenSite(BaseSite):
    """Handler for Discourse-based forums (forum.regen.network, regencommons.discourse.group)"""

    def extract_publication_date(self, soup: BeautifulSoup, url: str) -> Tuple[Optional[datetime], float]:
        """
        Extract publication date from Discourse forum pages

        Discourse has structured date information in:
        - <time> elements with datetime attributes
        - Meta tags for articles
        - Post metadata
        """
        published_at = None
        confidence = 0.0

        # Priority 1: Look for time elements with datetime attributes
        time_elements = soup.find_all(['time', 'relative-time'])
        for elem in time_elements:
            datetime_attr = elem.get('datetime')
            if datetime_attr:
                try:
                    from dateutil import parser
                    published_at = parser.parse(datetime_attr)
                    confidence = 0.95  # Very high confidence - structured data
                    self.logger.debug(f"Found Discourse datetime attribute: {datetime_attr}")
                    break
                except:
                    pass

        # Priority 2: Check meta tags for article published time
        if not published_at:
            meta_published = soup.find('meta', {'property': 'article:published_time'})
            if meta_published:
                content = meta_published.get('content')
                if content:
                    try:
                        from dateutil import parser
                        published_at = parser.parse(content)
                        confidence = 0.9
                        self.logger.debug(f"Found article published time in meta: {content}")
                    except:
                        pass

        # Priority 3: Look for date in post metadata
        if not published_at:
            post_meta = soup.find('div', class_='post-meta')
            if post_meta:
                date_text = post_meta.get_text()
                # Try to parse various date formats
                try:
                    from dateutil import parser
                    published_at = parser.parse(date_text, fuzzy=True)
                    confidence = 0.8
                    self.logger.debug(f"Extracted date from post metadata: {date_text}")
                except:
                    pass

        # Priority 4: Look for relative dates in topic list
        if not published_at and '/latest' not in url and '/categories' not in url:
            # This is likely a topic page
            date_elements = soup.find_all(['span', 'div'],
                                         attrs={'class': re.compile(r'relative-date|activity|created-at')})
            for elem in date_elements:
                date_str = elem.get_text(strip=True)
                if date_str:
                    # Handle relative dates
                    if 'ago' in date_str.lower():
                        confidence = 0.7  # Lower confidence for relative dates
                        # For now, skip relative dates - they're not reliable
                        continue
                    else:
                        try:
                            from dateutil import parser
                            published_at = parser.parse(date_str, fuzzy=True)
                            confidence = 0.75
                            self.logger.debug(f"Found date text in Discourse: {date_str}")
                            break
                        except:
                            pass

        return published_at, confidence

    def should_extract_content(self, url: str) -> bool:
        """
        Determine if this Discourse URL should have content extracted

        Extract from:
        - Individual topic/thread pages (/t/[slug]/[id])
        - Category pages with descriptions

        Skip:
        - User profiles (/u/)
        - Latest topics list (/latest)
        - Categories index
        """
        # Skip user profiles
        if '/u/' in url or '/users/' in url:
            return False

        # Skip index/list pages
        if any(x in url for x in ['/latest', '/top', '/categories', '/tags']):
            return False

        # Extract topic pages
        if '/t/' in url:
            return True

        # Extract category pages (they have descriptions)
        if '/c/' in url:
            return True

        return True

    def extract_metadata(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """Extract Discourse-specific metadata"""
        metadata = {}

        # Identify if this is a topic or category
        if '/t/' in url:
            metadata['content_type'] = 'forum_topic'

            # Extract topic metadata
            topic_meta = soup.find('div', class_='topic-meta-data')
            if topic_meta:
                # Try to get number of replies
                reply_count = soup.find('span', class_='reply-count')
                if reply_count:
                    try:
                        metadata['reply_count'] = int(reply_count.get_text().strip())
                    except:
                        pass

                # Try to get likes
                like_count = soup.find('span', class_='like-count')
                if like_count:
                    try:
                        metadata['like_count'] = int(like_count.get_text().strip())
                    except:
                        pass

            # Extract category
            category_elem = soup.find('a', class_='category-name')
            if category_elem:
                metadata['category'] = category_elem.get_text().strip()

            # Extract tags
            tags = []
            tag_elements = soup.find_all('a', class_='discourse-tag')
            for tag in tag_elements:
                tags.append(tag.get_text().strip())
            if tags:
                metadata['tags'] = tags

        elif '/c/' in url:
            metadata['content_type'] = 'forum_category'

            # Extract category description
            desc_elem = soup.find('div', class_='category-description')
            if desc_elem:
                metadata['description'] = desc_elem.get_text().strip()[:500]  # Limit length

        else:
            metadata['content_type'] = 'forum_page'

        # Extract author if available
        author_elem = soup.find('span', class_='creator') or soup.find('a', class_='username')
        if author_elem:
            metadata['author'] = author_elem.get_text().strip()

        return metadata

    def get_links_to_follow(self, soup: BeautifulSoup, url: str) -> List[str]:
        """
        Get links to follow from Discourse pages

        Strategy:
        - From category pages, follow topics
        - From topic lists, follow individual topics
        - Don't follow user profiles or external links
        """
        links = []
        base_url = f"https://{self.domain}"

        for link in soup.find_all('a', href=True):
            href = link['href']

            # Convert relative URLs to absolute
            if href.startswith('/'):
                href = base_url + href
            elif not href.startswith(('http://', 'https://')):
                continue

            # Only follow links on same domain
            if self.domain not in href:
                continue

            # Skip user profiles and auth pages
            if any(x in href for x in ['/u/', '/users/', '/login', '/signup', '/password-reset']):
                continue

            # Skip pagination and anchors
            if '?page=' in href or '#' in href:
                href = href.split('?')[0].split('#')[0]

            # Prioritize topic pages
            if '/t/' in href:
                links.append(href)
            # Follow category pages (they have content)
            elif '/c/' in href and '/latest' not in href:
                links.append(href)

        return list(set(links))  # Remove duplicates

    def extract_content_text(self, soup: BeautifulSoup, url: str) -> str:
        """
        Extract the main content from Discourse pages

        For topics, focus on the post content
        For categories, get the description
        """
        content = ""

        if '/t/' in url:
            # Extract post content
            post_elements = soup.find_all('div', class_='cooked')
            if post_elements:
                content_parts = []
                for post in post_elements:
                    # Remove blockquotes to avoid duplication
                    for blockquote in post.find_all('blockquote'):
                        blockquote.decompose()
                    content_parts.append(post.get_text().strip())
                content = "\n\n".join(content_parts)
            else:
                # Fallback to default extraction
                content = super().extract_content_text(soup, url)

        elif '/c/' in url:
            # Extract category description
            desc = soup.find('div', class_='category-description')
            if desc:
                content = desc.get_text().strip()
            else:
                content = super().extract_content_text(soup, url)

        else:
            content = super().extract_content_text(soup, url)

        return content

    def identify_content_type(self, soup: BeautifulSoup, url: str) -> str:
        """Identify Discourse content types"""
        if '/t/' in url:
            return 'forum_topic'
        elif '/c/' in url:
            return 'forum_category'
        elif '/latest' in url or '/top' in url:
            return 'forum_index'
        else:
            return 'forum_page'