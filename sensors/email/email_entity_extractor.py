"""
Entity Extractor for Email Sensor
Extracts Person, Organization, Project, and Concept entities from emails
"""

import logging
import os
import re
from typing import List, Dict, Any, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


# Common email domains to skip for organization extraction
COMMON_EMAIL_DOMAINS = {
    'gmail.com', 'googlemail.com', 'yahoo.com', 'yahoo.co.uk',
    'hotmail.com', 'hotmail.co.uk', 'outlook.com', 'outlook.co.uk',
    'live.com', 'msn.com', 'icloud.com', 'me.com', 'mac.com',
    'aol.com', 'protonmail.com', 'proton.me', 'tutanota.com',
    'fastmail.com', 'zoho.com', 'mail.com', 'gmx.com', 'gmx.net',
    'yandex.com', 'yandex.ru', 'qq.com', '163.com', '126.com',
}

# Domain to organization name mappings
DOMAIN_TO_ORG = {
    'regen.network': 'Regen Network',
    'regen.foundation': 'Regen Foundation',
    'cosmos.network': 'Cosmos Network',
    'interchain.io': 'Interchain Foundation',
    'tendermint.com': 'Tendermint',
    'anthropic.com': 'Anthropic',
    'openai.com': 'OpenAI',
    'google.com': 'Google',
    'microsoft.com': 'Microsoft',
    'github.com': 'GitHub',
}


def is_valid_person_name(name: str) -> bool:
    """Check if name is a valid person name (not just email prefix).

    Shared guard for From-header Person extraction — used by
    EmailEntityExtractor._is_valid_name() and by
    EmailSensor._extract_entities() (sensors/email/email_sensor.py) so both
    extraction paths apply the same validation instead of the sensor
    re-implementing a second, weaker check.
    """
    if not name:
        return False

    # Skip if it looks like an email address
    if '@' in name:
        return False

    # Skip if too short
    if len(name) < 3:
        return False

    # Skip if all lowercase with no spaces (likely username)
    if name.islower() and ' ' not in name:
        return False

    # Skip common non-names
    skip_patterns = [
        r'^no[-_]?reply',
        r'^support',
        r'^info',
        r'^admin',
        r'^sales',
        r'^team',
        r'^hello',
        r'^contact',
    ]
    for pattern in skip_patterns:
        if re.match(pattern, name.lower()):
            return False

    return True


class EmailEntityExtractor:
    """
    Extract entities from email headers and body.

    Extraction sources:
    1. From/To/Cc headers → Person entities
    2. Email domains → Organization entities
    3. LLM extraction from body → Organizations, Projects, Concepts
    """

    def __init__(
        self,
        llm_provider: str = 'openai',
        llm_model: str = 'gpt-4o-mini',
        extract_from_headers: bool = True,
        extract_from_body: bool = True,
        max_body_length: int = 4000,
    ):
        """
        Initialize entity extractor.

        Args:
            llm_provider: 'openai' or 'anthropic'
            llm_model: Model name for LLM extraction
            extract_from_headers: Extract from email headers
            extract_from_body: Use LLM for body extraction
            max_body_length: Max chars to send to LLM
        """
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self.extract_from_headers = extract_from_headers
        self.extract_from_body = extract_from_body
        self.max_body_length = max_body_length

        # Get API key
        if llm_provider == 'openai':
            self.api_key = os.getenv('OPENAI_API_KEY', '')
        else:
            self.api_key = os.getenv('ANTHROPIC_API_KEY', '')

        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=60.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()

    def extract_from_email(self, email_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract entities from email headers (synchronous).

        Args:
            email_data: Parsed email dict

        Returns:
            List of extracted entity dicts
        """
        entities = []

        if not self.extract_from_headers:
            return entities

        # Extract Person entities from From header
        from_name = email_data.get('from_name', '')
        from_address = email_data.get('from_address', '')

        if from_name and self._is_valid_name(from_name):
            entities.append({
                'name': from_name,
                'type': 'Person',
                'confidence': 0.95,
                'context': f'Email sender: {from_address}',
                'mentions': [from_name],
            })

        # Extract Organization from sender domain
        org = self._extract_org_from_domain(from_address)
        if org:
            entities.append({
                'name': org['name'],
                'type': 'Organization',
                'confidence': org['confidence'],
                'context': f'Sender domain: {org["domain"]}',
                'mentions': [org['name']],
            })

        # Extract from To/Cc (lower confidence since we may not have full names)
        for addr in email_data.get('to_addresses', []):
            org = self._extract_org_from_domain(addr)
            if org and org['name'] not in [e['name'] for e in entities]:
                entities.append({
                    'name': org['name'],
                    'type': 'Organization',
                    'confidence': org['confidence'] * 0.8,  # Lower confidence for recipients
                    'context': f'Recipient domain: {org["domain"]}',
                    'mentions': [org['name']],
                })

        return entities

    def _is_valid_name(self, name: str) -> bool:
        """Check if name is a valid person name (not just email prefix).

        Delegates to the module-level is_valid_person_name() so this guard
        and the one used by EmailSensor (sensors/email/email_sensor.py)
        can never drift apart.
        """
        return is_valid_person_name(name)

    def _extract_org_from_domain(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Extract organization from email domain.

        Args:
            email: Email address

        Returns:
            Dict with 'name', 'domain', 'confidence' or None
        """
        if not email or '@' not in email:
            return None

        domain = email.split('@')[1].lower()

        # Skip common providers
        if domain in COMMON_EMAIL_DOMAINS:
            return None

        # Check known mappings
        if domain in DOMAIN_TO_ORG:
            return {
                'name': DOMAIN_TO_ORG[domain],
                'domain': domain,
                'confidence': 0.95,
            }

        # Extract org name from domain
        # Handle subdomains (e.g., mail.company.com → company)
        parts = domain.split('.')
        if len(parts) >= 2:
            # Skip common TLDs and country codes
            main_part = parts[-2] if parts[-1] in ['com', 'org', 'net', 'io', 'co', 'ai'] else parts[0]

            # Clean up the name
            org_name = main_part.replace('-', ' ').replace('_', ' ')
            org_name = org_name.title()

            # Skip if too short
            if len(org_name) < 3:
                return None

            return {
                'name': org_name,
                'domain': domain,
                'confidence': 0.7,
            }

        return None

    async def extract_from_body(
        self,
        body_text: str,
        subject: str = '',
    ) -> List[Dict[str, Any]]:
        """
        Extract entities from email body using LLM.

        Args:
            body_text: Email body text
            subject: Email subject

        Returns:
            List of extracted entity dicts
        """
        if not self.extract_from_body or not self.api_key:
            return []

        if not body_text or len(body_text.strip()) < 50:
            return []

        # Truncate body for API
        text = body_text[:self.max_body_length]
        if subject:
            text = f"Subject: {subject}\n\n{text}"

        prompt = self._build_extraction_prompt(text)

        try:
            if self.llm_provider == 'openai':
                entities = await self._extract_openai(prompt)
            else:
                entities = await self._extract_anthropic(prompt)

            return entities

        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            return []

    def _build_extraction_prompt(self, text: str) -> str:
        """Build extraction prompt for LLM."""
        return f"""Extract named entities from this email. Return JSON array with entities.

Entity types to extract:
- Organization: Companies, institutions, non-profits, government agencies
- Project: Named projects, initiatives, programs
- Concept: Key topics, technologies, methodologies

Do NOT extract:
- Person names (handled separately)
- Generic terms
- Common words

Email:
---
{text}
---

Return valid JSON array. Example:
[
  {{"name": "Regen Network", "type": "Organization", "confidence": 0.9}},
  {{"name": "Carbon Credit Program", "type": "Project", "confidence": 0.8}},
  {{"name": "Regenerative Agriculture", "type": "Concept", "confidence": 0.85}}
]

Return empty array [] if no entities found.
JSON:"""

    async def _extract_openai(self, prompt: str) -> List[Dict[str, Any]]:
        """Extract using OpenAI API."""
        response = await self._client.post(
            'https://api.openai.com/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'model': self.llm_model,
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0.1,
                'max_tokens': 500,
            },
        )

        if response.status_code != 200:
            logger.error(f"OpenAI API error: {response.status_code}")
            return []

        data = response.json()
        content = data['choices'][0]['message']['content']

        return self._parse_entities(content)

    async def _extract_anthropic(self, prompt: str) -> List[Dict[str, Any]]:
        """Extract using Anthropic API."""
        response = await self._client.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': self.api_key,
                'anthropic-version': '2023-06-01',
                'Content-Type': 'application/json',
            },
            json={
                'model': self.llm_model,
                'max_tokens': 500,
                'messages': [{'role': 'user', 'content': prompt}],
            },
        )

        if response.status_code != 200:
            logger.error(f"Anthropic API error: {response.status_code}")
            return []

        data = response.json()
        content = data['content'][0]['text']

        return self._parse_entities(content)

    def _parse_entities(self, content: str) -> List[Dict[str, Any]]:
        """Parse LLM response into entity list."""
        import json

        try:
            # Find JSON array in response
            content = content.strip()

            # Handle markdown code blocks
            if '```json' in content:
                content = content.split('```json')[1].split('```')[0]
            elif '```' in content:
                content = content.split('```')[1].split('```')[0]

            entities = json.loads(content)

            # Validate and clean
            valid = []
            for e in entities:
                if not isinstance(e, dict):
                    continue
                if 'name' not in e or 'type' not in e:
                    continue
                if e['type'] not in ['Organization', 'Project', 'Concept']:
                    continue

                valid.append({
                    'name': e['name'],
                    'type': e['type'],
                    'confidence': e.get('confidence', 0.8),
                    'mentions': [e['name']],
                })

            return valid

        except json.JSONDecodeError:
            logger.debug(f"Failed to parse LLM response as JSON: {content[:200]}")
            return []

    async def extract_all(
        self,
        email_data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Extract all entities from email (headers + body).

        Args:
            email_data: Parsed email dict

        Returns:
            Combined list of entities
        """
        # Header extraction (synchronous)
        entities = self.extract_from_email(email_data)

        # Body extraction (async, LLM)
        body = email_data.get('body_text', '')
        subject = email_data.get('subject', '')

        body_entities = await self.extract_from_body(body, subject)

        # Merge, avoiding duplicates
        seen_names = {e['name'].lower() for e in entities}
        for e in body_entities:
            if e['name'].lower() not in seen_names:
                entities.append(e)
                seen_names.add(e['name'].lower())

        return entities
