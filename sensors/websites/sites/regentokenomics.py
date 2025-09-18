"""
Site-specific handler for regentokenomics.org
"""

from datetime import datetime
from typing import Optional, Tuple, Dict, Any, List
from bs4 import BeautifulSoup
import re
from .base_site import BaseSite


class RegentokenomicsSite(BaseSite):
    """Handler for regentokenomics.org - tokenomics DAO site with meeting pages"""

    def extract_publication_date(self, soup: BeautifulSoup, url: str) -> Tuple[Optional[datetime], float]:
        """
        Extract publication date for regentokenomics pages

        This site has:
        - Weekly meetup pages at /weekly-meetups/[date]
        - Project pages without specific dates
        - General governance pages without dates
        """
        published_at = None
        confidence = 0.0

        # Check if this is a weekly meetup page
        if '/weekly-meetups/' in url:
            # Extract date from URL pattern: /weekly-meetups/2024-11-15 or /weekly-meetups/sep-16
            match = re.search(r'/weekly-meetups/(\d{4}-\d{2}-\d{2})', url)
            if match:
                try:
                    published_at = datetime.strptime(match.group(1), '%Y-%m-%d')
                    confidence = 0.95  # High confidence - URL is the source of truth
                    self.logger.debug(f"Extracted meetup date from URL: {match.group(1)}")
                except:
                    pass

            # Check for month abbreviation pattern like /weekly-meetups/sep-16
            if not published_at:
                match = re.search(r'/weekly-meetups/([a-z]{3}-\d{1,2})', url, re.IGNORECASE)
                if match:
                    # We have month abbreviation but need year - look in content
                    month_day = match.group(1)
                    self.logger.debug(f"Found month-day pattern in URL: {month_day}")

            # If not in URL or need full date, look for date in the page content
            if not published_at:
                # Look for "Date of Session" pattern specifically
                content_text = soup.get_text()
                # Match patterns like "Date of Session September 16, 2025" or just "September 16, 2025"
                # Note: Sometimes text is concatenated without spaces, so we handle that too
                date_patterns = [
                    r'Date of Session\s*([A-Za-z]+ \d{1,2}, \d{4})',  # With or without space
                    r'([A-Za-z]+ \d{1,2}, \d{4})',  # General date pattern
                    r'(\d{4}-\d{2}-\d{2})'  # ISO date pattern
                ]

                for pattern in date_patterns:
                    date_match = re.search(pattern, content_text)
                    if date_match:
                        try:
                            date_str = date_match.group(1)
                            if '-' in date_str:  # YYYY-MM-DD format
                                published_at = datetime.strptime(date_str, '%Y-%m-%d')
                            else:  # "Month DD, YYYY" format
                                published_at = datetime.strptime(date_str, '%B %d, %Y')
                            confidence = 0.90 if 'Date of Session' in date_match.group(0) else 0.85
                            self.logger.debug(f"Extracted meetup date from content: {date_str}")
                            break
                        except:
                            pass

                # Also check headings as fallback
                if not published_at:
                    headings = soup.find_all(['h1', 'h2', 'h3'])
                    for heading in headings:
                        text = heading.get_text()
                        # Match patterns like "November 15, 2024" or "2024-11-15"
                        date_match = re.search(r'(\w+ \d{1,2}, \d{4})|(\d{4}-\d{2}-\d{2})', text)
                        if date_match:
                            try:
                                if date_match.group(1):  # "Month DD, YYYY" format
                                    published_at = datetime.strptime(date_match.group(1), '%B %d, %Y')
                                else:  # "YYYY-MM-DD" format
                                    published_at = datetime.strptime(date_match.group(2), '%Y-%m-%d')
                                confidence = 0.80
                                self.logger.debug(f"Extracted meetup date from heading: {date_match.group()}")
                                break
                            except:
                                pass

        # For project pages and reports, dates are less relevant
        # These are living documents that get updated
        elif any(x in url for x in ['/projects/', '/reports/', '/executive-summary']):
            # Don't extract dates for these pages - they're not time-specific content
            self.logger.debug(f"Skipping date extraction for project/report page: {url}")
            return None, 0.0

        # For other pages, return None - no date needed
        return published_at, confidence

    def should_extract_content(self, url: str) -> bool:
        """
        Determine if this URL should have its content extracted

        Extract content from:
        - Meeting pages (have actual content)
        - Project pages (have descriptions)
        - Executive summaries and reports

        Skip:
        - Main index page (just navigation)
        - Member list pages
        """
        # Skip index/navigation pages
        if url.endswith('regentokenomics.org/') or url.endswith('/members'):
            return False

        # Extract meeting pages, projects, reports
        if any(x in url for x in ['/weekly-meetups/', '/projects/', '/reports/',
                                   '/executive-summary', '/ethics-guidelines']):
            return True

        return True  # Default to extracting

    def extract_metadata(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """Extract regentokenomics-specific metadata"""
        metadata = {}

        # Identify content type
        if '/weekly-meetups/' in url:
            metadata['content_type'] = 'meeting'
            metadata['meeting_type'] = 'weekly_tokenomics'

            # Try to extract attendees from the page
            attendees = []
            # Look for a section with attendees or participants
            for elem in soup.find_all(['p', 'div', 'ul']):
                text = elem.get_text().lower()
                if 'attendee' in text or 'participant' in text or 'present' in text:
                    # Extract names (this is site-specific logic)
                    names = re.findall(r'[A-Z][a-z]+ [A-Z][a-z]+', elem.get_text())
                    attendees.extend(names)

            if attendees:
                metadata['attendees'] = list(set(attendees))  # Remove duplicates

        elif '/projects/' in url:
            metadata['content_type'] = 'project'

            # Try to extract project status
            status_elem = soup.find(text=re.compile(r'Status:', re.I))
            if status_elem:
                metadata['project_status'] = status_elem.parent.get_text().replace('Status:', '').strip()

        elif '/reports/' in url or '/executive-summary' in url:
            metadata['content_type'] = 'report'

        else:
            metadata['content_type'] = 'governance'

        # Extract any notion-specific metadata if this is from Notion
        notion_meta = soup.find('meta', {'property': 'notion:page_id'})
        if notion_meta:
            metadata['notion_page_id'] = notion_meta.get('content')

        return metadata

    def get_links_to_follow(self, soup: BeautifulSoup, url: str) -> List[str]:
        """
        Get links to follow from regentokenomics pages

        Custom logic:
        - From main page, follow links to projects and meetings
        - From meeting list, follow individual meeting pages
        - Don't follow external links
        """
        links = []

        for link in soup.find_all('a', href=True):
            href = link['href']

            # Convert relative URLs to absolute
            if href.startswith('/'):
                href = f"https://{self.domain}{href}"
            elif not href.startswith(('http://', 'https://')):
                continue

            # Only follow links on same domain
            if 'regentokenomics.org' not in href:
                continue

            # Skip anchors and parameters
            if '#' in href:
                href = href.split('#')[0]
            if not href:
                continue

            # Prioritize content pages
            if any(x in href for x in ['/weekly-meetups/', '/projects/', '/reports/',
                                       '/executive-summary', '/ethics-guidelines']):
                links.append(href)
            # Skip member pages and external links
            elif '/members/' not in href and 'twitter.com' not in href:
                links.append(href)

        return list(set(links))  # Remove duplicates

    def identify_content_type(self, soup: BeautifulSoup, url: str) -> str:
        """Identify the type of content on regentokenomics pages"""
        if '/weekly-meetups/' in url:
            return 'meeting'
        elif '/projects/' in url:
            return 'project'
        elif '/reports/' in url or '/executive-summary' in url:
            return 'report'
        elif '/ethics-guidelines' in url:
            return 'governance'
        elif url.endswith('/'):
            return 'index'
        else:
            return 'page'