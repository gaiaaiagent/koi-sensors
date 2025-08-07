"""
Document processor for chunking and preparing documents for embedding
"""

import re
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import hashlib
from loguru import logger
from dataclasses import dataclass, field
import json


@dataclass
class DocumentChunk:
    """
    Represents a chunk of a document ready for embedding
    """
    chunk_id: str  # Unique identifier for this chunk
    document_id: str  # Parent document ID
    content: str  # Chunk text content
    metadata: Dict[str, Any] = field(default_factory=dict)
    position: int = 0  # Position in original document
    token_count: int = 0  # Estimated token count
    
    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps({
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "content": self.content,
            "metadata": self.metadata,
            "position": self.position,
            "token_count": self.token_count
        }, indent=2)


class DocumentProcessor:
    """
    Processes documents into chunks for embedding generation
    """
    
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        """
        Initialize document processor
        
        Args:
            chunk_size: Target size for each chunk in tokens
            chunk_overlap: Number of tokens to overlap between chunks
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = 50  # Minimum chunk size in tokens
        
        # Simple token estimation (4 chars per token average)
        self.chars_per_token = 4
        
        logger.info(f"Initialized DocumentProcessor (chunk_size={chunk_size}, overlap={chunk_overlap})")
    
    def process_document(self, document: Dict[str, Any]) -> List[DocumentChunk]:
        """
        Process a document into chunks
        
        Args:
            document: Document dictionary with 'id', 'content', 'title', etc.
            
        Returns:
            List of DocumentChunk objects
        """
        doc_id = document.get('id', '')
        content = document.get('content', '')
        title = document.get('title', '')
        source = document.get('source', '')
        
        if not content or len(content.strip()) < self.min_chunk_size * self.chars_per_token:
            logger.debug(f"Skipping document {doc_id} - content too short")
            return []
        
        # Clean and prepare content
        content = self.clean_content(content)
        
        # Add title to content for context
        if title:
            content = f"# {title}\n\n{content}"
        
        # Split into chunks
        chunks = self.create_chunks(content, doc_id)
        
        # Add metadata to each chunk
        for i, chunk in enumerate(chunks):
            chunk.metadata.update({
                'document_title': title,
                'document_source': source,
                'document_url': document.get('url', ''),
                'chunk_index': i,
                'total_chunks': len(chunks)
            })
        
        logger.debug(f"Processed document {doc_id} into {len(chunks)} chunks")
        return chunks
    
    def clean_content(self, content: str) -> str:
        """
        Clean and normalize document content
        
        Args:
            content: Raw content
            
        Returns:
            Cleaned content
        """
        # Remove excessive whitespace
        content = re.sub(r'\n{3,}', '\n\n', content)
        content = re.sub(r' {2,}', ' ', content)
        
        # Remove non-printable characters
        content = ''.join(char for char in content if char.isprintable() or char in '\n\t')
        
        # Fix common markdown issues
        content = re.sub(r'#{7,}', '######', content)  # Limit heading depth
        
        return content.strip()
    
    def create_chunks(self, content: str, doc_id: str) -> List[DocumentChunk]:
        """
        Split content into overlapping chunks
        
        Args:
            content: Document content
            doc_id: Document ID
            
        Returns:
            List of DocumentChunk objects
        """
        chunks = []
        
        # Estimate tokens
        total_chars = len(content)
        chunk_size_chars = self.chunk_size * self.chars_per_token
        overlap_chars = self.chunk_overlap * self.chars_per_token
        
        # Try to split on natural boundaries
        sections = self.split_into_sections(content)
        
        current_chunk = ""
        current_position = 0
        
        for section in sections:
            # If section is small enough, add to current chunk
            if len(current_chunk) + len(section) <= chunk_size_chars:
                current_chunk += section + "\n\n"
            else:
                # If current chunk is not empty, save it
                if current_chunk.strip():
                    chunk_id = self.generate_chunk_id(doc_id, current_position)
                    chunks.append(DocumentChunk(
                        chunk_id=chunk_id,
                        document_id=doc_id,
                        content=current_chunk.strip(),
                        position=current_position,
                        token_count=len(current_chunk) // self.chars_per_token
                    ))
                    current_position += 1
                    
                    # Start new chunk with overlap
                    if self.chunk_overlap > 0 and chunks:
                        # Take last part of previous chunk as overlap
                        overlap_text = current_chunk[-overlap_chars:]
                        current_chunk = overlap_text
                    else:
                        current_chunk = ""
                
                # If section itself is too large, split it further
                if len(section) > chunk_size_chars:
                    sub_chunks = self.split_large_section(section, chunk_size_chars, overlap_chars)
                    for sub_chunk in sub_chunks:
                        chunk_id = self.generate_chunk_id(doc_id, current_position)
                        chunks.append(DocumentChunk(
                            chunk_id=chunk_id,
                            document_id=doc_id,
                            content=sub_chunk.strip(),
                            position=current_position,
                            token_count=len(sub_chunk) // self.chars_per_token
                        ))
                        current_position += 1
                else:
                    current_chunk = section + "\n\n"
        
        # Don't forget the last chunk
        if current_chunk.strip():
            chunk_id = self.generate_chunk_id(doc_id, current_position)
            chunks.append(DocumentChunk(
                chunk_id=chunk_id,
                document_id=doc_id,
                content=current_chunk.strip(),
                position=current_position,
                token_count=len(current_chunk) // self.chars_per_token
            ))
        
        return chunks
    
    def split_into_sections(self, content: str) -> List[str]:
        """
        Split content into logical sections
        
        Args:
            content: Document content
            
        Returns:
            List of content sections
        """
        sections = []
        
        # Split by headers (markdown style)
        header_pattern = r'^#+\s+.*$'
        
        lines = content.split('\n')
        current_section = []
        
        for line in lines:
            if re.match(header_pattern, line):
                # Save current section if not empty
                if current_section:
                    sections.append('\n'.join(current_section))
                    current_section = []
                # Start new section with header
                current_section.append(line)
            else:
                current_section.append(line)
        
        # Add last section
        if current_section:
            sections.append('\n'.join(current_section))
        
        # If no headers found, split by paragraphs
        if len(sections) <= 1:
            sections = content.split('\n\n')
        
        return [s for s in sections if s.strip()]
    
    def split_large_section(self, section: str, chunk_size: int, overlap_size: int) -> List[str]:
        """
        Split a large section into smaller chunks
        
        Args:
            section: Section content
            chunk_size: Target chunk size in characters
            overlap_size: Overlap size in characters
            
        Returns:
            List of chunk strings
        """
        chunks = []
        
        # Try to split on sentence boundaries
        sentences = re.split(r'(?<=[.!?])\s+', section)
        
        current_chunk = ""
        for sentence in sentences:
            if len(current_chunk) + len(sentence) <= chunk_size:
                current_chunk += sentence + " "
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    # Add overlap
                    if overlap_size > 0 and len(current_chunk) > overlap_size:
                        current_chunk = current_chunk[-overlap_size:] + sentence + " "
                    else:
                        current_chunk = sentence + " "
                else:
                    # Single sentence is too long, split by words
                    words = sentence.split()
                    for i in range(0, len(words), chunk_size // 10):  # Rough estimate
                        chunk = ' '.join(words[i:i + chunk_size // 10])
                        if chunk:
                            chunks.append(chunk)
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks
    
    def generate_chunk_id(self, doc_id: str, position: int) -> str:
        """
        Generate unique chunk ID
        
        Args:
            doc_id: Document ID
            position: Chunk position
            
        Returns:
            Unique chunk ID
        """
        data = f"{doc_id}:{position}"
        return hashlib.md5(data.encode()).hexdigest()[:12]
    
    def process_batch(self, documents: List[Dict[str, Any]]) -> List[DocumentChunk]:
        """
        Process multiple documents in batch
        
        Args:
            documents: List of document dictionaries
            
        Returns:
            List of all chunks from all documents
        """
        all_chunks = []
        
        for doc in documents:
            try:
                chunks = self.process_document(doc)
                all_chunks.extend(chunks)
            except Exception as e:
                logger.error(f"Error processing document {doc.get('id', 'unknown')}: {e}")
                continue
        
        logger.info(f"Processed {len(documents)} documents into {len(all_chunks)} chunks")
        return all_chunks