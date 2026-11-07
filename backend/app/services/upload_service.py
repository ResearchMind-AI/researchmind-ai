"""
Upload your own papers (PDF or DOCX) into a session.

Text is extracted, the LLM reads the first pages to fill in title / authors /
year / abstract, and the full text is chunked and embedded for this session.
Uploaded papers then feed into themes, gaps, chat and exports like any other.
"""
import logging
import os
from datetime import datetime
from typing import Dict

from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.models.paper import Paper, PaperSource, SessionPaper
from app.services.embedding_service import EmbeddingService
from app.services.llm import LLMClient
from app.services.text_extraction import TextExtractor
from app.services.vector_store import VectorStoreService

logger = logging.getLogger(__name__)

MAX_CHUNKS_PER_UPLOAD = 80


class UploadError(Exception):
    pass


async def extract_metadata(text: str, filename: str, file_meta: Dict) -> Dict:
    head = text[:5000]
    prompt = f"""TASK: paper_metadata
Below is the start of an academic paper (file name: {filename}).
Extract: "title", "authors" (list of names), "year" (integer or null), "abstract" (verbatim
if present, otherwise a 3-sentence summary of the text). Return JSON only.

{head}"""
    try:
        data = await LLMClient().complete_json(prompt, max_tokens=900)
    except Exception as e:
        logger.warning(f"Metadata extraction failed: {e}")
        data = {}
    title = (data.get("title") or file_meta.get("title") or os.path.splitext(filename)[0]).strip()
    authors = data.get("authors") or ([file_meta["author"]] if file_meta.get("author") else None)
    year = data.get("year") if isinstance(data.get("year"), int) else None
    return {"title": title[:1000], "authors": authors, "year": year, "abstract": data.get("abstract")}


async def add_uploaded_paper(db: DBSession, session_id: int, user_id: int,
                             filename: str, data: bytes) -> Paper:
    if len(data) > settings.MAX_UPLOAD_SIZE:
        raise UploadError(f"File is larger than {settings.MAX_UPLOAD_SIZE // (1024 * 1024)} MB.")
    ext = os.path.splitext(filename)[1].lower()
    try:
        if ext == ".pdf":
            extracted = TextExtractor.extract_pdf_bytes(data)
        elif ext == ".docx":
            extracted = TextExtractor.extract_docx_bytes(data)
        else:
            raise UploadError("Only PDF and DOCX files are supported.")
    except UploadError:
        raise
    except Exception as e:
        raise UploadError(f"Could not read the file: {e}") from e

    text = extracted["full_text"]
    if len(text) < 200:
        raise UploadError("Almost no text could be extracted. Scanned PDFs (images) are not supported yet.")

    meta = await extract_metadata(text, filename, extracted.get("metadata", {}))
    paper = Paper(
        title=meta["title"], abstract=meta["abstract"], authors=meta["authors"],
        publication_date=datetime(meta["year"], 1, 1) if meta["year"] else None,
        source=PaperSource.MANUAL_UPLOAD, full_text=text,
        extra_metadata={"uploaded": True, "filename": filename, "found_in": ["upload"]},
        embedding_model=settings.EMBEDDING_MODEL,
    )
    db.add(paper)
    db.flush()
    db.add(SessionPaper(session_id=session_id, paper_id=paper.id, added_by_user_id=user_id,
                        relevance_score=5, notes="Uploaded by user"))
    db.flush()

    embedder = EmbeddingService()
    doc = f"Title: {paper.title}\n\nAbstract: {paper.abstract or ''}\n\nFull Text: {text}"
    chunks = embedder.chunk_text(doc)[:MAX_CHUNKS_PER_UPLOAD]
    vectors = await embedder.generate_embeddings_batch(chunks)
    await VectorStoreService(db).add_paper_embeddings(session_id, paper.id, chunks, vectors)
    paper.embedding_generated = True
    db.commit()
    return paper
