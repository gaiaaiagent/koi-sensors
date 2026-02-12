"""
Text Chunker for Email Sensor
Splits email content into chunks for embedding
"""

import logging
import re
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class EmailChunker:
    """
    Split email text into chunks suitable for embedding.

    Uses a simple token-based chunking strategy with overlap.
    Tokens are approximated as whitespace-separated words.
    """

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        min_chunk_size: int = 100,
    ):
        """
        Initialize chunker.

        Args:
            chunk_size: Target chunk size in tokens
            chunk_overlap: Overlap between chunks in tokens
            min_chunk_size: Minimum chunk size to emit
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

    def tokenize(self, text: str) -> List[str]:
        """
        Simple tokenization by whitespace.

        Args:
            text: Input text

        Returns:
            List of tokens
        """
        # Split on whitespace, keeping punctuation attached
        return text.split()

    def detokenize(self, tokens: List[str]) -> str:
        """
        Join tokens back into text.

        Args:
            tokens: List of tokens

        Returns:
            Joined text
        """
        return ' '.join(tokens)

    def chunk_text(self, text: str) -> List[Dict[str, Any]]:
        """
        Split text into overlapping chunks.

        Args:
            text: Input text

        Returns:
            List of chunk dicts with 'text', 'index', 'start_token', 'end_token'
        """
        if not text or not text.strip():
            return []

        tokens = self.tokenize(text)
        total_tokens = len(tokens)

        # If text is short enough, return as single chunk
        if total_tokens <= self.chunk_size:
            return [{
                'text': text.strip(),
                'index': 0,
                'start_token': 0,
                'end_token': total_tokens,
                'total_chunks': 1,
            }]

        chunks = []
        start = 0
        chunk_index = 0

        while start < total_tokens:
            end = min(start + self.chunk_size, total_tokens)

            # Get chunk tokens
            chunk_tokens = tokens[start:end]
            chunk_text = self.detokenize(chunk_tokens)

            # Only emit if chunk meets minimum size
            if len(chunk_tokens) >= self.min_chunk_size or start == 0:
                chunks.append({
                    'text': chunk_text,
                    'index': chunk_index,
                    'start_token': start,
                    'end_token': end,
                })
                chunk_index += 1

            # Move start position, accounting for overlap
            start = end - self.chunk_overlap

            # Prevent infinite loop if overlap >= chunk_size
            if start <= chunks[-1]['start_token'] if chunks else 0:
                start = end

        # Update total chunks count
        for chunk in chunks:
            chunk['total_chunks'] = len(chunks)

        logger.debug(f"Split {total_tokens} tokens into {len(chunks)} chunks")
        return chunks

    def chunk_email(self, email_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Chunk an email, including subject as context.

        Args:
            email_data: Parsed email dict with 'subject', 'body_text', etc.

        Returns:
            List of chunks with email context
        """
        subject = email_data.get('subject', '')
        body = email_data.get('body_text', '')

        # Combine subject with body for context
        full_text = f"Subject: {subject}\n\n{body}" if subject else body

        chunks = self.chunk_text(full_text)

        # Add email metadata to each chunk
        for chunk in chunks:
            chunk['message_id'] = email_data.get('message_id')
            chunk['subject'] = subject
            chunk['from_address'] = email_data.get('from_address')
            chunk['date_sent'] = email_data.get('date_sent')

        return chunks


class SentenceAwareChunker(EmailChunker):
    """
    Chunk text while respecting sentence boundaries.

    Tries to end chunks at sentence boundaries for better coherence.
    """

    # Regex for sentence endings
    SENTENCE_END = re.compile(r'[.!?]\s+')

    def chunk_text(self, text: str) -> List[Dict[str, Any]]:
        """
        Split text into chunks, trying to respect sentence boundaries.

        Args:
            text: Input text

        Returns:
            List of chunk dicts
        """
        if not text or not text.strip():
            return []

        tokens = self.tokenize(text)
        total_tokens = len(tokens)

        # If text is short enough, return as single chunk
        if total_tokens <= self.chunk_size:
            return [{
                'text': text.strip(),
                'index': 0,
                'start_token': 0,
                'end_token': total_tokens,
                'total_chunks': 1,
            }]

        chunks = []
        start = 0
        chunk_index = 0

        while start < total_tokens:
            target_end = min(start + self.chunk_size, total_tokens)

            # Try to find a sentence boundary near the target end
            end = self._find_sentence_boundary(tokens, start, target_end)

            # Get chunk tokens
            chunk_tokens = tokens[start:end]
            chunk_text = self.detokenize(chunk_tokens)

            if len(chunk_tokens) >= self.min_chunk_size or start == 0:
                chunks.append({
                    'text': chunk_text,
                    'index': chunk_index,
                    'start_token': start,
                    'end_token': end,
                })
                chunk_index += 1

            # Move start position
            start = max(end - self.chunk_overlap, start + 1)

        # Update total chunks count
        for chunk in chunks:
            chunk['total_chunks'] = len(chunks)

        return chunks

    def _find_sentence_boundary(
        self,
        tokens: List[str],
        start: int,
        target_end: int,
    ) -> int:
        """
        Find a sentence boundary near target_end.

        Looks backwards from target_end for a sentence-ending token.
        """
        # Search window: look back up to 20% of chunk size
        search_start = max(start, target_end - self.chunk_size // 5)

        for i in range(target_end - 1, search_start - 1, -1):
            token = tokens[i]
            # Check if token ends with sentence punctuation
            if token.endswith('.') or token.endswith('!') or token.endswith('?'):
                return i + 1

        # No sentence boundary found, use target end
        return target_end
