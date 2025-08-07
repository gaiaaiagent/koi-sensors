"""
Embedder for generating vector embeddings from document chunks
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings
from loguru import logger
import json
from tqdm import tqdm
import torch


class Embedder:
    """
    Generates and manages vector embeddings for document chunks
    """
    
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """
        Initialize embedder with specified model
        
        Args:
            model_name: Name of the sentence-transformer model to use
        """
        self.model_name = model_name
        
        # Check for GPU availability
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        logger.info(f"Using device: {self.device}")
        
        # Load model
        logger.info(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name, device=self.device)
        
        # Get model dimensions
        self.embedding_dim = self.model.get_sentence_embedding_dimension()
        logger.info(f"Embedding dimension: {self.embedding_dim}")
        
        # Storage paths
        self.embeddings_path = Path("/home/regenai/project/indexing/storage/embeddings")
        self.embeddings_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize ChromaDB for vector storage
        self.chroma_path = Path("/home/regenai/project/indexing/storage/chromadb")
        self.chroma_path.mkdir(parents=True, exist_ok=True)
        
        self.chroma_client = chromadb.PersistentClient(
            path=str(self.chroma_path),
            settings=Settings(anonymized_telemetry=False)
        )
        
        # Get or create collection
        try:
            self.collection = self.chroma_client.get_collection("regen_documents")
            logger.info("Using existing ChromaDB collection")
        except:
            self.collection = self.chroma_client.create_collection(
                name="regen_documents",
                metadata={"description": "Regen Network document embeddings"}
            )
            logger.info("Created new ChromaDB collection")
    
    def generate_embedding(self, text: str) -> np.ndarray:
        """
        Generate embedding for a single text
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector as numpy array
        """
        # Truncate if too long (model has max sequence length)
        max_length = 512  # For MiniLM
        if len(text) > max_length * 4:  # Rough char estimate
            text = text[:max_length * 4]
        
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding
    
    def generate_embeddings(self, texts: List[str], batch_size: int = 32) -> np.ndarray:
        """
        Generate embeddings for multiple texts
        
        Args:
            texts: List of texts to embed
            batch_size: Batch size for processing
            
        Returns:
            Array of embeddings
        """
        logger.info(f"Generating embeddings for {len(texts)} texts")
        
        # Process in batches for efficiency
        embeddings = []
        
        for i in tqdm(range(0, len(texts), batch_size), desc="Generating embeddings"):
            batch = texts[i:i + batch_size]
            
            # Truncate long texts
            max_length = 512 * 4
            batch = [text[:max_length] if len(text) > max_length else text for text in batch]
            
            batch_embeddings = self.model.encode(
                batch,
                convert_to_numpy=True,
                show_progress_bar=False,
                batch_size=batch_size
            )
            embeddings.append(batch_embeddings)
        
        return np.vstack(embeddings)
    
    def process_chunks(self, chunks: List[Any], batch_size: int = 32) -> Dict[str, np.ndarray]:
        """
        Process document chunks and generate embeddings
        
        Args:
            chunks: List of DocumentChunk objects
            batch_size: Batch size for processing
            
        Returns:
            Dictionary mapping chunk_id to embedding
        """
        if not chunks:
            logger.warning("No chunks to process")
            return {}
        
        # Extract texts and IDs
        texts = [chunk.content for chunk in chunks]
        chunk_ids = [chunk.chunk_id for chunk in chunks]
        
        # Generate embeddings
        embeddings = self.generate_embeddings(texts, batch_size)
        
        # Create mapping
        embedding_map = {}
        for chunk_id, embedding in zip(chunk_ids, embeddings):
            embedding_map[chunk_id] = embedding
        
        logger.info(f"Generated {len(embedding_map)} embeddings")
        return embedding_map
    
    def save_embeddings(self, embedding_map: Dict[str, np.ndarray]) -> List[Path]:
        """
        Save embeddings to disk
        
        Args:
            embedding_map: Dictionary mapping chunk_id to embedding
            
        Returns:
            List of saved file paths
        """
        saved_paths = []
        
        for chunk_id, embedding in embedding_map.items():
            file_path = self.embeddings_path / f"{chunk_id}.npy"
            np.save(file_path, embedding)
            saved_paths.append(file_path)
        
        logger.debug(f"Saved {len(saved_paths)} embeddings to disk")
        return saved_paths
    
    def load_embedding(self, chunk_id: str) -> Optional[np.ndarray]:
        """
        Load a saved embedding
        
        Args:
            chunk_id: Chunk ID
            
        Returns:
            Embedding array or None if not found
        """
        file_path = self.embeddings_path / f"{chunk_id}.npy"
        
        if file_path.exists():
            return np.load(file_path)
        return None
    
    def add_to_chromadb(self, chunks: List[Any], embeddings: Dict[str, np.ndarray]):
        """
        Add chunks and embeddings to ChromaDB for vector search
        
        Args:
            chunks: List of DocumentChunk objects
            embeddings: Dictionary mapping chunk_id to embedding
        """
        if not chunks:
            return
        
        # Prepare data for ChromaDB
        ids = []
        documents = []
        metadatas = []
        embeddings_list = []
        
        for chunk in chunks:
            if chunk.chunk_id not in embeddings:
                logger.warning(f"No embedding found for chunk {chunk.chunk_id}")
                continue
            
            ids.append(chunk.chunk_id)
            documents.append(chunk.content)
            metadatas.append({
                "document_id": chunk.document_id,
                "position": str(chunk.position),
                "token_count": str(chunk.token_count),
                **{k: str(v) for k, v in chunk.metadata.items()}  # Convert all to strings
            })
            embeddings_list.append(embeddings[chunk.chunk_id].tolist())
        
        # Add to collection
        if ids:
            self.collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings_list
            )
            logger.info(f"Added {len(ids)} chunks to ChromaDB")
    
    def search(self, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """
        Search for similar documents using vector similarity
        
        Args:
            query: Search query
            n_results: Number of results to return
            
        Returns:
            List of search results with metadata
        """
        # Generate embedding for query
        query_embedding = self.generate_embedding(query)
        
        # Search in ChromaDB
        results = self.collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=n_results
        )
        
        # Format results
        formatted_results = []
        for i in range(len(results['ids'][0])):
            formatted_results.append({
                'chunk_id': results['ids'][0][i],
                'content': results['documents'][0][i],
                'metadata': results['metadatas'][0][i],
                'distance': results['distances'][0][i] if 'distances' in results else None
            })
        
        return formatted_results
    
    def process_and_store(self, chunks: List[Any], batch_size: int = 32):
        """
        Complete pipeline: process chunks, generate embeddings, and store
        
        Args:
            chunks: List of DocumentChunk objects
            batch_size: Batch size for processing
        """
        if not chunks:
            logger.warning("No chunks to process")
            return
        
        # Generate embeddings
        embedding_map = self.process_chunks(chunks, batch_size)
        
        # Save embeddings to disk
        self.save_embeddings(embedding_map)
        
        # Add to ChromaDB
        self.add_to_chromadb(chunks, embedding_map)
        
        logger.success(f"Processed and stored {len(chunks)} chunks")
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about stored embeddings
        
        Returns:
            Dictionary with statistics
        """
        # Count saved embeddings
        embedding_files = list(self.embeddings_path.glob("*.npy"))
        
        # Get ChromaDB collection info
        collection_count = self.collection.count()
        
        return {
            "model": self.model_name,
            "embedding_dimension": self.embedding_dim,
            "device": self.device,
            "embeddings_on_disk": len(embedding_files),
            "chunks_in_chromadb": collection_count,
            "storage_path": str(self.embeddings_path),
            "chromadb_path": str(self.chroma_path)
        }