"""
Embedder for Email Sensor
Calls existing BGE server for embeddings
"""

import logging
from typing import List, Dict, Any, Optional
import httpx

logger = logging.getLogger(__name__)


class EmailEmbedder:
    """
    Generate embeddings using the existing BGE server.

    The BGE server provides 1024-dimensional embeddings compatible with
    the koi_embeddings and koi_memory_chunks tables.
    """

    def __init__(
        self,
        bge_server_url: str = "http://localhost:8351/embed",
        dimension: int = 1024,
        batch_size: int = 20,
        doc_embedding_tokens: int = 512,
        timeout: float = 30.0,
    ):
        """
        Initialize embedder.

        Args:
            bge_server_url: URL of the BGE embedding server
            dimension: Expected embedding dimension (1024 for BGE)
            batch_size: Number of texts to embed in one request
            doc_embedding_tokens: Max tokens for doc-level embedding
            timeout: HTTP request timeout in seconds
        """
        self.bge_server_url = bge_server_url
        self.dimension = dimension
        self.batch_size = batch_size
        self.doc_embedding_tokens = doc_embedding_tokens
        self.timeout = timeout

        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        """Async context manager entry."""
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def embed_text(self, text: str) -> Optional[List[float]]:
        """
        Embed a single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector or None on error
        """
        result = await self.embed_batch([text])
        return result[0] if result else None

    async def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """
        Embed multiple texts.

        Note: The embedding server handles one text at a time, so we call it
        sequentially. The server has internal caching for performance.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors (None for failures)
        """
        if not texts:
            return []

        client = self._get_client()
        results: List[Optional[List[float]]] = []

        for text in texts:
            try:
                response = await client.post(
                    self.bge_server_url,
                    json={"text": text},
                )

                if response.status_code == 200:
                    data = response.json()
                    embedding = data.get("embedding")

                    if embedding and len(embedding) == self.dimension:
                        results.append(embedding)
                    else:
                        logger.warning(f"Invalid embedding dimension: {len(embedding) if embedding else 0}")
                        results.append(None)
                else:
                    logger.error(f"Embedding request failed: {response.status_code}")
                    results.append(None)

            except Exception as e:
                logger.error(f"Embedding failed: {e}")
                results.append(None)

        success_count = sum(1 for r in results if r is not None)
        logger.debug(f"Embedded {success_count}/{len(texts)} texts")

        return results

    def truncate_for_doc_embedding(self, text: str) -> str:
        """
        Truncate text to first N tokens for doc-level embedding.

        Args:
            text: Full text

        Returns:
            Truncated text
        """
        # Simple token approximation: split by whitespace
        tokens = text.split()

        if len(tokens) <= self.doc_embedding_tokens:
            return text

        # Truncate and rejoin
        truncated = ' '.join(tokens[:self.doc_embedding_tokens])
        logger.debug(f"Truncated {len(tokens)} tokens to {self.doc_embedding_tokens}")
        return truncated

    async def embed_email_doc(self, email_data: Dict[str, Any]) -> Optional[List[float]]:
        """
        Generate doc-level embedding for an email.

        Uses first doc_embedding_tokens of content.

        Args:
            email_data: Parsed email dict

        Returns:
            Doc-level embedding vector
        """
        subject = email_data.get('subject', '')
        body = email_data.get('body_text', '')

        # Combine subject and body
        full_text = f"Subject: {subject}\n\n{body}" if subject else body

        # Truncate for doc embedding
        doc_text = self.truncate_for_doc_embedding(full_text)

        return await self.embed_text(doc_text)

    async def embed_chunks(
        self,
        chunks: List[Dict[str, Any]],
    ) -> List[Optional[List[float]]]:
        """
        Embed multiple chunks.

        Args:
            chunks: List of chunk dicts with 'text' field

        Returns:
            List of embeddings (None for failures)
        """
        texts = [chunk.get('text', '') for chunk in chunks]
        return await self.embed_batch(texts)


class DirectBGEEmbedder(EmailEmbedder):
    """
    Alternative embedder that calls BGE model directly.

    Use this if the BGE server is not available.
    Requires: sentence-transformers, torch
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-large-en-v1.5",
        device: str = "cpu",
        **kwargs,
    ):
        """
        Initialize direct BGE embedder.

        Args:
            model_name: HuggingFace model name
            device: PyTorch device (cpu/cuda)
        """
        super().__init__(**kwargs)
        self.model_name = model_name
        self.device = device
        self._model = None
        self._tokenizer = None

    def _load_model(self):
        """Lazy-load the model."""
        if self._model is not None:
            return

        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading BGE model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name, device=self.device)
            logger.info("BGE model loaded")
        except ImportError:
            raise ImportError(
                "sentence-transformers required for direct embedding. "
                "Install with: pip install sentence-transformers"
            )

    async def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Embed texts using local model."""
        if not texts:
            return []

        self._load_model()

        try:
            embeddings = self._model.encode(
                texts,
                batch_size=self.batch_size,
                show_progress_bar=False,
                normalize_embeddings=True,
            )

            # Convert to list of lists
            return [emb.tolist() for emb in embeddings]

        except Exception as e:
            logger.error(f"Direct embedding failed: {e}")
            return [None] * len(texts)
