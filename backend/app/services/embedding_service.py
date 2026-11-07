"""
Embedding generation service using OpenAI
"""
import logging
from typing import List, Optional
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Service for generating embeddings using OpenAI"""

    def __init__(self):
        if settings.OFFLINE_DEMO:
            from app.services.offline import FakeEmbeddings
            self.client = FakeEmbeddings()
        else:
            self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.EMBEDDING_MODEL
        self.chunk_size = settings.CHUNK_SIZE
        self.chunk_overlap = settings.CHUNK_OVERLAP

    async def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding for a single text

        Args:
            text: Text to embed

        Returns:
            Embedding vector as list of floats
        """
        try:
            response = await self.client.embeddings.create(
                input=text,
                model=self.model
            )

            embedding = response.data[0].embedding
            logger.info(f"Generated embedding for text (length: {len(text)})")
            return embedding

        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            raise

    async def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts in a batch

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        try:
            embeddings: List[List[float]] = []
            for start in range(0, len(texts), 96):  # stay well under API batch limits
                batch = [t[:8000] for t in texts[start:start + 96]]
                response = await self.client.embeddings.create(input=batch, model=self.model)
                embeddings.extend(d.embedding for d in response.data)
            logger.info(f"Generated {len(embeddings)} embeddings")
            return embeddings

        except Exception as e:
            logger.error(f"Error generating batch embeddings: {e}")
            raise

    def chunk_text(self, text: str) -> List[str]:
        """
        Split text into chunks for embedding

        Args:
            text: Text to chunk

        Returns:
            List of text chunks
        """
        if not text:
            return []

        # Simple chunking by character count
        # In production, you might want to use more sophisticated chunking
        # that respects sentence/paragraph boundaries

        chunks = []
        start = 0
        text_length = len(text)

        while start < text_length:
            # Calculate end position
            end = start + self.chunk_size

            # If this is not the last chunk, try to break at a space
            if end < text_length:
                # Look for a space within the last 100 characters
                space_pos = text.rfind(' ', end - 100, end)
                if space_pos > start:
                    end = space_pos

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            # Move start position with overlap
            start = end - self.chunk_overlap

        logger.info(f"Split text into {len(chunks)} chunks")
        return chunks

    async def embed_document(self, text: str, title: Optional[str] = None) -> tuple[List[str], List[List[float]]]:
        """
        Chunk and embed a full document

        Args:
            text: Document text
            title: Optional document title to prepend to first chunk

        Returns:
            Tuple of (chunks, embeddings)
        """
        # Add title to first chunk if provided
        if title:
            text = f"Title: {title}\n\n{text}"

        # Chunk the text
        chunks = self.chunk_text(text)

        if not chunks:
            return [], []

        # Generate embeddings for all chunks
        embeddings = await self.generate_embeddings_batch(chunks)

        logger.info(f"Embedded document into {len(chunks)} chunks")
        return chunks, embeddings

    async def embed_paper(
        self,
        title: str,
        abstract: Optional[str] = None,
        full_text: Optional[str] = None
    ) -> tuple[List[str], List[List[float]]]:
        """
        Generate embeddings for a research paper

        Args:
            title: Paper title
            abstract: Paper abstract
            full_text: Full paper text

        Returns:
            Tuple of (chunks, embeddings)
        """
        # Build document text with structured sections
        doc_parts = [f"Title: {title}"]

        if abstract:
            doc_parts.append(f"Abstract: {abstract}")

        if full_text:
            doc_parts.append(f"Full Text: {full_text}")

        document = "\n\n".join(doc_parts)

        # Chunk and embed
        chunks = self.chunk_text(document)

        if not chunks:
            logger.warning(f"No chunks generated for paper: {title}")
            return [], []

        embeddings = await self.generate_embeddings_batch(chunks)

        logger.info(f"Embedded paper '{title}' into {len(chunks)} chunks")
        return chunks, embeddings
