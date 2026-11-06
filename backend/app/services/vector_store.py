"""
Vector store backed by the SQL database.

Chunks and their embeddings are stored per session in the `paper_chunks`
table and searched with cosine similarity in numpy. A POC session holds at
most a few thousand chunks, so this is fast, needs no extra service, and
works the same on PostgreSQL (AWS RDS) and SQLite. It replaces ChromaDB.
"""
import logging
from typing import Any, Dict, List, Optional

import numpy as np
from sqlalchemy.orm import Session as DBSession

from app.core.database import SessionLocal
from app.models.research import PaperChunk

logger = logging.getLogger(__name__)


def cosine_scores(matrix: np.ndarray, query: np.ndarray) -> np.ndarray:
    """Cosine similarity of each row of `matrix` with `query`."""
    if matrix.size == 0:
        return np.array([])
    m_norm = np.linalg.norm(matrix, axis=1)
    q_norm = np.linalg.norm(query) or 1.0
    m_norm[m_norm == 0] = 1.0
    return (matrix @ query) / (m_norm * q_norm)


class VectorStoreService:
    """Store and search per-session paper chunk embeddings."""

    def __init__(self, db: Optional[DBSession] = None):
        self._own = db is None
        self.db = db or SessionLocal()

    def close(self):
        if self._own:
            self.db.close()

    async def add_paper_embeddings(
        self,
        session_id: int,
        paper_id: int,
        chunks: List[str],
        embeddings: List[List[float]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Replace this paper's chunks in this session with new ones."""
        self.db.query(PaperChunk).filter(
            PaperChunk.session_id == session_id, PaperChunk.paper_id == paper_id
        ).delete()
        for i, (text, emb) in enumerate(zip(chunks, embeddings)):
            self.db.add(PaperChunk(session_id=session_id, paper_id=paper_id,
                                   chunk_index=i, text=text, embedding=list(map(float, emb))))
        self.db.commit()

    def has_embeddings(self, session_id: int, paper_id: int) -> bool:
        return self.db.query(PaperChunk.id).filter(
            PaperChunk.session_id == session_id, PaperChunk.paper_id == paper_id
        ).first() is not None

    def search(self, session_id: int, query_embedding: List[float], n_results: int = 8,
               paper_ids: Optional[List[int]] = None) -> List[Dict[str, Any]]:
        q = self.db.query(PaperChunk).filter(PaperChunk.session_id == session_id)
        if paper_ids:
            q = q.filter(PaperChunk.paper_id.in_(paper_ids))
        rows = q.all()
        if not rows:
            return []
        matrix = np.array([r.embedding for r in rows], dtype=np.float32)
        scores = cosine_scores(matrix, np.array(query_embedding, dtype=np.float32))
        order = np.argsort(-scores)[:n_results]
        return [{"chunk_id": rows[i].id, "paper_id": rows[i].paper_id,
                 "chunk_index": rows[i].chunk_index, "text": rows[i].text,
                 "score": float(scores[i])} for i in order]

    async def search_papers(self, session_id: int, query_embedding: List[float],
                            n_results: int = 10, filter_metadata: Optional[Dict] = None):
        """Backwards-compatible wrapper around `search`."""
        return self.search(session_id, query_embedding, n_results)

    def paper_vectors(self, session_id: int) -> Dict[int, np.ndarray]:
        """Mean embedding per paper in the session (used for clustering)."""
        rows = self.db.query(PaperChunk.paper_id, PaperChunk.embedding).filter(
            PaperChunk.session_id == session_id).all()
        grouped: Dict[int, List[List[float]]] = {}
        for pid, emb in rows:
            grouped.setdefault(pid, []).append(emb)
        return {pid: np.mean(np.array(embs, dtype=np.float32), axis=0) for pid, embs in grouped.items()}

    async def delete_paper_embeddings(self, session_id: int, paper_id: int) -> None:
        self.db.query(PaperChunk).filter(
            PaperChunk.session_id == session_id, PaperChunk.paper_id == paper_id
        ).delete()
        self.db.commit()

    async def delete_session_collection(self, session_id: int) -> None:
        self.db.query(PaperChunk).filter(PaperChunk.session_id == session_id).delete()
        self.db.commit()

    async def get_collection_stats(self, session_id: int) -> Dict[str, Any]:
        count = self.db.query(PaperChunk).filter(PaperChunk.session_id == session_id).count()
        return {"session_id": session_id, "total_chunks": count}
