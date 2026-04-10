"""
Vector store service using ChromaDB
"""
import logging
from typing import List, Optional, Dict, Any
import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings

logger = logging.getLogger(__name__)


class VectorStoreService:
    """Service for managing vector embeddings in ChromaDB"""

    def __init__(self):
        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(
            path=settings.CHROMA_PERSIST_DIR,
            settings=ChromaSettings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        logger.info(f"Initialized ChromaDB at {settings.CHROMA_PERSIST_DIR}")

    def get_or_create_collection(self, session_id: int) -> chromadb.Collection:
        """
        Get or create a collection for a research session

        Args:
            session_id: Research session ID

        Returns:
            ChromaDB collection
        """
        collection_name = f"session_{session_id}"

        # ChromaDB collection names must be 3-63 characters and match pattern
        collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"session_id": str(session_id)}
        )

        logger.info(f"Got/created collection: {collection_name}")
        return collection

    async def add_paper_embeddings(
        self,
        session_id: int,
        paper_id: int,
        chunks: List[str],
        embeddings: List[List[float]],
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Add paper embeddings to session collection

        Args:
            session_id: Research session ID
            paper_id: Paper ID
            chunks: List of text chunks
            embeddings: List of embedding vectors
            metadata: Optional metadata to attach to chunks
        """
        try:
            collection = self.get_or_create_collection(session_id)

            # Build IDs and metadata for each chunk
            ids = [f"paper_{paper_id}_chunk_{i}" for i in range(len(chunks))]

            # Build metadata for each chunk
            metadatas = []
            for i in range(len(chunks)):
                chunk_metadata = {
                    "paper_id": str(paper_id),
                    "chunk_index": i,
                    "total_chunks": len(chunks)
                }
                if metadata:
                    chunk_metadata.update(metadata)
                metadatas.append(chunk_metadata)

            # Add to collection
            collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=chunks,
                metadatas=metadatas
            )

            logger.info(f"Added {len(chunks)} chunks for paper {paper_id} to session {session_id}")

        except Exception as e:
            logger.error(f"Error adding embeddings to vector store: {e}")
            raise

    async def search_papers(
        self,
        session_id: int,
        query_embedding: List[float],
        n_results: int = 10,
        filter_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Search for relevant paper chunks in a session

        Args:
            session_id: Research session ID
            query_embedding: Query embedding vector
            n_results: Number of results to return
            filter_metadata: Optional metadata filter

        Returns:
            Dictionary containing search results
        """
        try:
            collection = self.get_or_create_collection(session_id)

            # Query the collection
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=filter_metadata,
                include=["documents", "metadatas", "distances"]
            )

            # Format results
            formatted_results = {
                "chunks": results["documents"][0] if results["documents"] else [],
                "metadatas": results["metadatas"][0] if results["metadatas"] else [],
                "distances": results["distances"][0] if results["distances"] else []
            }

            logger.info(f"Found {len(formatted_results['chunks'])} results for session {session_id}")
            return formatted_results

        except Exception as e:
            logger.error(f"Error searching vector store: {e}")
            raise

    async def delete_paper_embeddings(
        self,
        session_id: int,
        paper_id: int
    ) -> None:
        """
        Delete all embeddings for a paper from a session

        Args:
            session_id: Research session ID
            paper_id: Paper ID to delete
        """
        try:
            collection = self.get_or_create_collection(session_id)

            # Delete all chunks for this paper
            collection.delete(
                where={"paper_id": str(paper_id)}
            )

            logger.info(f"Deleted embeddings for paper {paper_id} from session {session_id}")

        except Exception as e:
            logger.error(f"Error deleting embeddings from vector store: {e}")
            raise

    async def delete_session_collection(self, session_id: int) -> None:
        """
        Delete entire collection for a session

        Args:
            session_id: Research session ID
        """
        try:
            collection_name = f"session_{session_id}"
            self.client.delete_collection(name=collection_name)

            logger.info(f"Deleted collection for session {session_id}")

        except Exception as e:
            logger.error(f"Error deleting collection: {e}")
            raise

    async def get_collection_stats(self, session_id: int) -> Dict[str, Any]:
        """
        Get statistics about a session's vector collection

        Args:
            session_id: Research session ID

        Returns:
            Dictionary containing collection statistics
        """
        try:
            collection = self.get_or_create_collection(session_id)

            stats = {
                "name": collection.name,
                "count": collection.count(),
                "metadata": collection.metadata
            }

            return stats

        except Exception as e:
            logger.error(f"Error getting collection stats: {e}")
            raise

    async def update_paper_metadata(
        self,
        session_id: int,
        paper_id: int,
        metadata: Dict[str, Any]
    ) -> None:
        """
        Update metadata for all chunks of a paper

        Args:
            session_id: Research session ID
            paper_id: Paper ID
            metadata: New metadata to merge
        """
        try:
            collection = self.get_or_create_collection(session_id)

            # Get all chunks for this paper
            results = collection.get(
                where={"paper_id": str(paper_id)},
                include=["metadatas"]
            )

            if not results["ids"]:
                logger.warning(f"No chunks found for paper {paper_id} in session {session_id}")
                return

            # Update metadata for each chunk
            ids = results["ids"]
            metadatas = results["metadatas"]

            updated_metadatas = []
            for existing_metadata in metadatas:
                updated_metadata = existing_metadata.copy()
                updated_metadata.update(metadata)
                updated_metadatas.append(updated_metadata)

            collection.update(
                ids=ids,
                metadatas=updated_metadatas
            )

            logger.info(f"Updated metadata for {len(ids)} chunks of paper {paper_id}")

        except Exception as e:
            logger.error(f"Error updating metadata: {e}")
            raise
