"""
Site-specific handler for regen.foundation
"""

from datetime import datetime
from typing import Optional, Tuple, Dict, Any, List
from bs4 import BeautifulSoup
import re
from .base_site import BaseSite


class RegenFoundationSite(BaseSite):
    """Handler for regen.foundation and www.regen.foundation"""

    def extract_publication_date(self, soup: BeautifulSoup, url: str) -> Tuple[Optional[datetime], float]:
        """
        Extract publication date from Regen Foundation pages

        The foundation site has:
        - News/announcement pages with dates
        - Grant program pages (with application deadlines)
        - Static pages (about, team, etc.) without dates
        """
        published_at = None
        confidence = 0.0

        # Skip static pages that don't need dates
        static_pages = ['/about', '/team', '/mission', '/contact', '/governance']
        if any(page in url.lower() for page in static_pages):
            self.logger.debug(f"Skipping date extraction for static page: {url}")
            return None, 0.0

        # Priority 1: Look for news/announcement dates
        if '/news/' in url or '/announcements/' in url or '/blog/' in url:
            # Check for structured date in article header
            article_date = soup.find('time', {'datetime': True})
            if article_date:
                try:
                    from dateutil import parser
                    published_at = parser.parse(article_date['datetime'])
                    confidence = 0.95
                    self.logger.debug(f"Found article date: {article_date['datetime']}")
                except:
                    pass

            # Check for date in URL pattern
            if not published_at:
                # Match /news/2024/11/15/title or /news/2024-11-15-title
                match = re.search(r'/(?:news|announcements|blog)/(\d{4})[/-](\d{2})[/-](\d{2})', url)
                if match:
                    try:
                        year, month, day = match.groups()
                        published_at = datetime(int(year), int(month), int(day))
                        confidence = 0.85
                        self.logger.debug(f"Extracted date from URL: {year}-{month}-{day}")
                    except:
                        pass

        # Priority 2: Grant program pages - look for application deadlines
        elif '/grants/' in url or '/funding/' in url:
            # Look for deadline information
            deadline_patterns = [
                r'Application Deadline[:\s]+([A-Za-z]+ \d{1,2},? \d{4})',
                r'Deadline[:\s]+([A-Za-z]+ \d{1,2},? \d{4})',
                r'Applications? (?:close|due)[:\s]+([A-Za-z]+ \d{1,2},? \d{4})'
            ]

            for pattern in deadline_patterns:
                match = re.search(pattern, soup.get_text(), re.I)
                if match:
                    try:
                        from dateutil import parser
                        # This is a deadline, not published date, but still relevant
                        deadline = parser.parse(match.group(1))
                        # Don't use deadline as published date, but could store in metadata
                        self.logger.debug(f"Found grant deadline: {match.group(1)}")
                        # Return None for published_at but note the deadline in logs
                    except:
                        pass

            # For grant announcements, look for announcement date
            announce_elem = soup.find(text=re.compile(r'Announced', re.I))
            if announce_elem:
                parent = announce_elem.parent
                if parent:
                    date_text = parent.get_text()
                    try:
                        from dateutil import parser
                        published_at = parser.parse(date_text, fuzzy=True)
                        confidence = 0.75
                        self.logger.debug(f"Found grant announcement date: {date_text}")
                    except:
                        pass

        # Priority 3: Check meta tags for any page
        if not published_at:
            meta_published = soup.find('meta', {'property': 'article:published_time'})
            if meta_published:
                content = meta_published.get('content')
                if content:
                    try:
                        from dateutil import parser
                        published_at = parser.parse(content)
                        confidence = 0.9
                        self.logger.debug(f"Found meta published date: {content}")
                    except:
                        pass

        # Priority 4: Look for "Posted on" or "Published" text
        if not published_at:
            date_patterns = [
                r'Posted on[:\s]+([A-Za-z]+ \d{1,2},? \d{4})',
                r'Published[:\s]+([A-Za-z]+ \d{1,2},? \d{4})',
                r'Date[:\s]+([A-Za-z]+ \d{1,2},? \d{4})'
            ]

            for pattern in date_patterns:
                match = re.search(pattern, soup.get_text(), re.I)
                if match:
                    try:
                        from dateutil import parser
                        published_at = parser.parse(match.group(1))
                        confidence = 0.8
                        self.logger.debug(f"Found date pattern: {match.group(1)}")
                        break
                    except:
                        pass

        return published_at, confidence

    def should_extract_content(self, url: str) -> bool:
        """
        Determine if this URL should have content extracted

        Extract from:
        - News and announcements
        - Grant program pages
        - About/mission pages (important context)
        - Team pages

        Skip:
        - Login/auth pages
        - Pure navigation pages
        - External links
        """
        # Skip auth and utility pages
        if any(x in url.lower() for x in ['/login', '/auth', '/api/', '/search']):
            return False

        # Skip document downloads
        if any(url.endswith(ext) for ext in ['.pdf', '.doc', '.docx', '.zip']):
            return False

        # Extract all other foundation content
        return True

    def extract_metadata(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """Extract Regen Foundation specific metadata"""
        metadata = {}

        # Identify content type
        if '/news/' in url or '/announcements/' in url:
            metadata['content_type'] = 'news'

            # Extract news category if available
            category_elem = soup.find('span', class_='category') or \
                          soup.find('a', class_='category-link')
            if category_elem:
                metadata['category'] = category_elem.get_text().strip()

        elif '/grants/' in url or '/funding/' in url:
            metadata['content_type'] = 'grant_program'

            # Extract grant details
            # Look for grant amount
            amount_match = re.search(r'\$[\d,]+(?:\.\d{2})?', soup.get_text())
            if amount_match:
                metadata['grant_amount'] = amount_match.group()

            # Look for application deadline
            deadline_match = re.search(
                r'(?:Application )?Deadline[:\s]+([A-Za-z]+ \d{1,2},? \d{4})',
                soup.get_text(), re.I
            )
            if deadline_match:
                metadata['application_deadline'] = deadline_match.group(1)

            # Extract grant type/name
            grant_title = soup.find('h1')
            if grant_title:
                title_text = grant_title.get_text().strip()
                if 'grant' in title_text.lower():
                    metadata['grant_name'] = title_text

        elif '/team/' in url or '/about/' in url:
            metadata['content_type'] = 'organizational'

            # For team pages, extract member names
            if '/team/' in url:
                team_members = []
                # Look for team member cards or bios
                member_elements = soup.find_all('div', class_=re.compile(r'team-member|member-card|bio'))
                for elem in member_elements:
                    name_elem = elem.find(['h3', 'h4', 'strong'])
                    if name_elem:
                        team_members.append(name_elem.get_text().strip())
                if team_members:
                    metadata['team_members'] = team_members[:20]  # Limit to 20 to avoid huge metadata

        elif '/governance/' in url:
            metadata['content_type'] = 'governance'

        else:
            metadata['content_type'] = 'page'

        # Extract author if present
        author_elem = soup.find('span', class_='author') or \
                     soup.find('meta', {'name': 'author'})
        if author_elem:
            if author_elem.name == 'meta':
                metadata['author'] = author_elem.get('content')
            else:
                metadata['author'] = author_elem.get_text().strip()

        # Extract tags if present
        tags = []
        tag_container = soup.find('div', class_='tags') or \
                       soup.find('ul', class_='tag-list')
        if tag_container:
            for tag in tag_container.find_all(['a', 'span', 'li']):
                tag_text = tag.get_text().strip()
                if tag_text and len(tag_text) < 50:  # Reasonable tag length
                    tags.append(tag_text)
        if tags:
            metadata['tags'] = tags

        return metadata

    def get_links_to_follow(self, soup: BeautifulSoup, url: str) -> List[str]:
        """
        Get links to follow from Regen Foundation pages

        Strategy:
        - Follow all internal foundation links
        - Don't follow external links
        - Skip document downloads
        """
        links = []
        base_url = "https://regen.foundation"

        for link in soup.find_all('a', href=True):
            href = link['href']

            # Handle www subdomain
            if 'www.regen.foundation' in url:
                base_url = "https://www.regen.foundation"

            # Convert relative URLs to absolute
            if href.startswith('/'):
                href = base_url + href
            elif not href.startswith(('http://', 'https://')):
                continue

            # Only follow foundation domain links
            if 'regen.foundation' not in href:
                continue

            # Skip documents and media files
            if any(href.endswith(ext) for ext in
                   ['.pdf', '.doc', '.docx', '.zip', '.jpg', '.png', '.gif']):
                continue

            # Skip auth pages
            if any(x in href for x in ['/login', '/auth', '/api/']):
                continue

            # Remove anchors and query parameters
            href = href.split('#')[0].split('?')[0]

            if href:
                links.append(href)

        return list(set(links))  # Remove duplicates

    def identify_content_type(self, soup: BeautifulSoup, url: str) -> str:
        """Identify the type of content on Regen Foundation pages"""
        if '/news/' in url or '/announcements/' in url or '/blog/' in url:
            return 'news'
        elif '/grants/' in url or '/funding/' in url:
            return 'grant_program'
        elif '/team/' in url:
            return 'team'
        elif '/about/' in url or '/mission/' in url:
            return 'about'
        elif '/governance/' in url:
            return 'governance'
        elif url.endswith('/'):
            return 'index'
        else:
            return 'page'