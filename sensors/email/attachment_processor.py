"""
Attachment Processor for Email Sensor
Extracts text from PDF and DOCX attachments
"""

import hashlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)


class AttachmentProcessor:
    """
    Process email attachments to extract text content.

    Supports:
    - PDF files (via pdfplumber)
    - DOCX files (via python-docx)
    - Plain text files
    - HTML files
    """

    SUPPORTED_TYPES = {
        'application/pdf': 'pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
        'text/plain': 'text',
        'text/html': 'html',
    }

    def __init__(
        self,
        max_size: int = 10 * 1024 * 1024,  # 10MB
        max_pages: int = 50,
        temp_dir: Optional[str] = None,
    ):
        """
        Initialize attachment processor.

        Args:
            max_size: Maximum attachment size to process
            max_pages: Maximum pages for PDF processing
            temp_dir: Directory for temporary files
        """
        self.max_size = max_size
        self.max_pages = max_pages
        self.temp_dir = temp_dir or tempfile.gettempdir()

        # Check for optional dependencies
        self._pdf_available = self._check_pdfplumber()
        self._docx_available = self._check_docx()

    def _check_pdfplumber(self) -> bool:
        """Check if pdfplumber is available."""
        try:
            import pdfplumber
            return True
        except ImportError:
            logger.warning("pdfplumber not installed - PDF extraction disabled")
            return False

    def _check_docx(self) -> bool:
        """Check if python-docx is available."""
        try:
            import docx
            return True
        except ImportError:
            logger.warning("python-docx not installed - DOCX extraction disabled")
            return False

    def can_process(self, content_type: str, size: int) -> bool:
        """
        Check if attachment can be processed.

        Args:
            content_type: MIME type
            size: File size in bytes

        Returns:
            True if processable
        """
        if size > self.max_size:
            return False

        if content_type not in self.SUPPORTED_TYPES:
            return False

        # Check dependencies for specific types
        file_type = self.SUPPORTED_TYPES[content_type]
        if file_type == 'pdf' and not self._pdf_available:
            return False
        if file_type == 'docx' and not self._docx_available:
            return False

        return True

    def extract_text(
        self,
        content: bytes,
        content_type: str,
        filename: str = 'attachment',
    ) -> Optional[str]:
        """
        Extract text from attachment.

        Args:
            content: Raw attachment bytes
            content_type: MIME type
            filename: Original filename

        Returns:
            Extracted text or None
        """
        if not content:
            return None

        file_type = self.SUPPORTED_TYPES.get(content_type)
        if not file_type:
            return None

        try:
            if file_type == 'pdf':
                return self._extract_pdf(content)
            elif file_type == 'docx':
                return self._extract_docx(content)
            elif file_type == 'text':
                return self._extract_text(content)
            elif file_type == 'html':
                return self._extract_html(content)
        except Exception as e:
            logger.error(f"Failed to extract from {filename}: {e}")
            return None

        return None

    def _extract_pdf(self, content: bytes) -> Optional[str]:
        """Extract text from PDF."""
        import pdfplumber
        import io

        text_parts = []

        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for i, page in enumerate(pdf.pages):
                    if i >= self.max_pages:
                        text_parts.append(f"\n[Truncated at {self.max_pages} pages]")
                        break

                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)

            return '\n\n'.join(text_parts) if text_parts else None

        except Exception as e:
            logger.error(f"PDF extraction error: {e}")
            return None

    def _extract_docx(self, content: bytes) -> Optional[str]:
        """Extract text from DOCX."""
        import docx
        import io

        try:
            doc = docx.Document(io.BytesIO(content))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return '\n\n'.join(paragraphs) if paragraphs else None

        except Exception as e:
            logger.error(f"DOCX extraction error: {e}")
            return None

    def _extract_text(self, content: bytes) -> Optional[str]:
        """Extract plain text."""
        try:
            # Try UTF-8 first, then fall back to latin-1
            try:
                return content.decode('utf-8')
            except UnicodeDecodeError:
                return content.decode('latin-1')
        except Exception:
            return None

    def _extract_html(self, content: bytes) -> Optional[str]:
        """Extract text from HTML."""
        import re

        try:
            # Decode
            try:
                html = content.decode('utf-8')
            except UnicodeDecodeError:
                html = content.decode('latin-1')

            # Remove scripts and styles
            html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)

            # Replace block elements with newlines
            html = re.sub(r'<(br|p|div|li|tr)[^>]*>', '\n', html, flags=re.IGNORECASE)

            # Remove tags
            html = re.sub(r'<[^>]+>', '', html)

            # Decode entities
            import html as html_module
            text = html_module.unescape(html)

            # Clean whitespace
            text = re.sub(r'\n\s*\n', '\n\n', text)
            text = re.sub(r' +', ' ', text)

            return text.strip() if text else None

        except Exception as e:
            logger.error(f"HTML extraction error: {e}")
            return None

    def process_from_email(
        self,
        email_msg,
        parent_message_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Process all attachments from an email message object.

        Args:
            email_msg: Email message object with attachments
            parent_message_id: Parent email's Message-ID

        Returns:
            List of processed attachment dicts with extracted text
        """
        results = []

        if not email_msg.is_multipart():
            return results

        attachment_index = 0

        for part in email_msg.walk():
            content_disposition = str(part.get('Content-Disposition', ''))

            if 'attachment' not in content_disposition:
                continue

            filename = part.get_filename() or f"attachment_{attachment_index}"
            content_type = part.get_content_type()

            try:
                payload = part.get_payload(decode=True)
                if not payload:
                    continue

                size = len(payload)
                content_hash = hashlib.sha256(payload).hexdigest()[:16]

                # Check if processable
                if not self.can_process(content_type, size):
                    logger.debug(f"Skipping unsupported attachment: {filename} ({content_type})")
                    results.append({
                        'index': attachment_index,
                        'filename': filename,
                        'content_type': content_type,
                        'size': size,
                        'content_hash': content_hash,
                        'extracted_text': None,
                        'processed': False,
                    })
                    attachment_index += 1
                    continue

                # Extract text
                extracted = self.extract_text(payload, content_type, filename)

                results.append({
                    'index': attachment_index,
                    'filename': filename,
                    'content_type': content_type,
                    'size': size,
                    'content_hash': content_hash,
                    'extracted_text': extracted,
                    'processed': True,
                    'text_length': len(extracted) if extracted else 0,
                })

                if extracted:
                    logger.info(f"Extracted {len(extracted)} chars from {filename}")

            except Exception as e:
                logger.error(f"Error processing attachment {filename}: {e}")

            attachment_index += 1

        return results

    def process_attachment_data(
        self,
        attachment_meta: Dict[str, Any],
        raw_content: bytes,
    ) -> Optional[str]:
        """
        Process a single attachment from metadata and content.

        Args:
            attachment_meta: Attachment metadata dict
            raw_content: Raw attachment bytes

        Returns:
            Extracted text or None
        """
        content_type = attachment_meta.get('content_type', '')
        filename = attachment_meta.get('filename', 'attachment')
        size = len(raw_content)

        if not self.can_process(content_type, size):
            return None

        return self.extract_text(raw_content, content_type, filename)
