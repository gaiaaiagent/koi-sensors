"""
Site-specific handler for regen.network and related subdomains
"""

from datetime import datetime
from typing import Optional, Tuple, Dict, Any, List
from bs4 import BeautifulSoup
import re
from .base_site import BaseSite


class RegenNetworkSite(BaseSite):
    """Handler for regen.network main site, docs, guides, and registry"""

    def extract_publication_date(self, soup: BeautifulSoup, url: str) -> Tuple[Optional[datetime], float]:
        """
        Extract publication date from Regen Network pages

        Strategy varies by subdomain:
        - docs.regen.network: Technical documentation (version dates)
        - guides.regen.network: Tutorial guides (last updated dates)
        - registry.regen.network: Project registry (creation dates)
        - Main site: Blog posts and announcements
        """
        published_at = None
        confidence = 0.0

        # Check subdomain
        if 'docs.regen.network' in url:
            # Documentation pages often have version/update info
            # Look for "Last updated" text
            for elem in soup.find_all(text=re.compile(r'Last\s+(updated|modified)', re.I)):
                parent = elem.parent
                if parent:
                    date_text = parent.get_text()
                    # Try to extract date after "Last updated"
                    match = re.search(r'Last\s+(?:updated|modified)[:\s]+(.+)', date_text, re.I)
                    if match:
                        try:
                            from dateutil import parser
                            published_at = parser.parse(match.group(1), fuzzy=True)
                            confidence = 0.7  # Medium confidence for docs
                            self.logger.debug(f"Found docs update date: {match.group(1)}")
                            break
                        except:
                            pass

        elif 'registry.regen.network' in url:
            # Registry pages have project creation dates
            # Look for creation date in project metadata
            creation_elem = soup.find('div', class_='creation-date') or \
                          soup.find('span', text=re.compile(r'Created', re.I))
            if creation_elem:
                date_text = creation_elem.get_text()
                try:
                    from dateutil import parser
                    published_at = parser.parse(date_text, fuzzy=True)
                    confidence = 0.85
                    self.logger.debug(f"Found registry creation date: {date_text}")
                except:
                    pass

        elif 'guides.regen.network' in url:
            # Guide pages may have publication dates
            # Similar to docs but with different patterns
            guide_meta = soup.find('div', class_='guide-meta')
            if guide_meta:
                date_text = guide_meta.get_text()
                try:
                    from dateutil import parser
                    published_at = parser.parse(date_text, fuzzy=True)
                    confidence = 0.75
                    self.logger.debug(f"Found guide date: {date_text}")
                except:
                    pass

        else:
            # Main regen.network site - blog posts and announcements
            # Priority 1: Look for article metadata
            article_time = soup.find('time', {'datetime': True})
            if article_time:
                try:
                    from dateutil import parser
                    published_at = parser.parse(article_time['datetime'])
                    confidence = 0.95
                    self.logger.debug(f"Found article time element: {article_time['datetime']}")
                except:
                    pass

            # Priority 2: Check meta tags
            if not published_at:
                meta_date = soup.find('meta', {'property': 'article:published_time'})
                if meta_date:
                    content = meta_date.get('content')
                    if content:
                        try:
                            from dateutil import parser
                            published_at = parser.parse(content)
                            confidence = 0.9
                            self.logger.debug(f"Found meta published date: {content}")
                        except:
                            pass

            # Priority 3: Look for blog post date in URL
            if not published_at and '/blog/' in url:
                # Match patterns like /blog/2024/11/title or /blog/2024-11-15-title
                match = re.search(r'/blog/(\d{4})[/-](\d{2})[/-](\d{2})', url)
                if match:
                    try:
                        year, month, day = match.groups()
                        published_at = datetime(int(year), int(month), int(day))
                        confidence = 0.85
                        self.logger.debug(f"Extracted blog date from URL: {year}-{month}-{day}")
                    except:
                        pass

        return published_at, confidence

    def should_extract_content(self, url: str) -> bool:
        """
        Determine if this URL should have content extracted

        Extract from:
        - Blog posts
        - Documentation pages
        - Guide pages
        - Registry project pages

        Skip:
        - Navigation/index pages
        - Search results
        - Login/auth pages
        """
        # Skip auth and utility pages
        if any(x in url for x in ['/login', '/auth', '/search', '/api/']):
            return False

        # Skip pure navigation pages
        if url.endswith('/') and url.count('/') <= 3:
            # Main index pages
            return False

        # Extract content pages
        if any(x in url for x in ['/blog/', '/docs/', '/guides/', '/registry/',
                                  '/about', '/resources', '/ecosystem']):
            return True

        return True

    def extract_metadata(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """Extract Regen Network specific metadata"""
        metadata = {}

        # Identify content type based on URL/subdomain
        if 'docs.regen.network' in url:
            metadata['content_type'] = 'documentation'

            # Try to extract version
            version_elem = soup.find('span', class_='version')
            if version_elem:
                metadata['version'] = version_elem.get_text().strip()

        elif 'guides.regen.network' in url:
            metadata['content_type'] = 'guide'

            # Extract guide category
            breadcrumb = soup.find('nav', class_='breadcrumb')
            if breadcrumb:
                categories = [a.get_text().strip() for a in breadcrumb.find_all('a')]
                if categories:
                    metadata['category'] = categories[-1] if categories else None

        elif 'registry.regen.network' in url:
            metadata['content_type'] = 'registry_project'

            # Extract project details
            project_name = soup.find('h1', class_='project-name')
            if project_name:
                metadata['project_name'] = project_name.get_text().strip()

            # Extract credit class if available
            credit_class = soup.find('span', class_='credit-class')
            if credit_class:
                metadata['credit_class'] = credit_class.get_text().strip()

        elif '/blog/' in url:
            metadata['content_type'] = 'blog_post'

            # Extract author
            author_elem = soup.find('span', class_='author') or \
                        soup.find('meta', {'name': 'author'})
            if author_elem:
                if author_elem.name == 'meta':
                    metadata['author'] = author_elem.get('content')
                else:
                    metadata['author'] = author_elem.get_text().strip()

            # Extract tags
            tags = []
            tag_container = soup.find('div', class_='tags') or soup.find('div', class_='post-tags')
            if tag_container:
                for tag in tag_container.find_all(['a', 'span'], class_=re.compile(r'tag')):
                    tags.append(tag.get_text().strip())
            if tags:
                metadata['tags'] = tags

        else:
            metadata['content_type'] = 'page'

        return metadata

    def get_links_to_follow(self, soup: BeautifulSoup, url: str) -> List[str]:
        """
        Get links to follow from Regen Network pages

        Strategy:
        - Follow internal links within the same subdomain
        - Follow links to other Regen subdomains
        - Don't follow external links
        """
        links = []

        # Determine current subdomain
        if 'docs.regen.network' in url:
            base_url = 'https://docs.regen.network'
        elif 'guides.regen.network' in url:
            base_url = 'https://guides.regen.network'
        elif 'registry.regen.network' in url:
            base_url = 'https://registry.regen.network'
        else:
            base_url = 'https://regen.network'

        for link in soup.find_all('a', href=True):
            href = link['href']

            # Convert relative URLs to absolute
            if href.startswith('/'):
                href = base_url + href
            elif not href.startswith(('http://', 'https://')) and not href.startswith('#'):
                # Relative path without leading slash
                href = base_url + '/' + href

            # Skip non-HTTP links and anchors
            if not href.startswith(('http://', 'https://')) or '#' in href:
                continue

            # Only follow Regen Network domains
            if not any(domain in href for domain in ['regen.network', 'docs.regen.network',
                                                      'guides.regen.network', 'registry.regen.network']):
                continue

            # Skip auth and utility pages
            if any(x in href for x in ['/login', '/auth', '/search', '/api/', '.pdf', '.zip']):
                continue

            links.append(href.split('#')[0])  # Remove anchors

        return list(set(links))  # Remove duplicates

    def identify_content_type(self, soup: BeautifulSoup, url: str) -> str:
        """Identify the type of content on Regen Network pages"""
        if 'docs.regen.network' in url:
            return 'documentation'
        elif 'guides.regen.network' in url:
            return 'guide'
        elif 'registry.regen.network' in url:
            if '/project/' in url:
                return 'registry_project'
            else:
                return 'registry_index'
        elif '/blog/' in url:
            return 'blog_post'
        elif url.endswith('/'):
            return 'index'
        else:
            return 'page'