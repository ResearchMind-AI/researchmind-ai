"""
Paper management endpoints
Handles paper search, ingestion, and management
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session as DBSession
import os
from datetime import datetime

from app.core.database import get_db
from app.models.user import User
from app.models.paper import Paper, SessionPaper, PaperSource
from app.models.session import Session, SessionMemberRole
from app.schemas.paper import (
    PaperSearchRequest,
    PaperSearchResponse,
    PaperSearchResult,
    PaperIngestRequest,
    PaperResponse,
    SessionPaperCreate,
    SessionPaperUpdate,
    SessionPaperResponse,
    PaperUploadResponse,
)
from app.api.deps import get_current_active_user
from app.api.v1.sessions import check_session_permission
from app.services.pubmed_service import PubMedService
from app.services.openalex_service import OpenAlexService
from app.services.text_extraction import TextExtractor
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStoreService
from app.services.discovery_service import parse_date, all_sources
from app.config import settings
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

# Viewers and reviewers are read-only (owner always has access)
EDIT_ROLES = [SessionMemberRole.LEAD, SessionMemberRole.CONTRIBUTOR]


@router.post("/search", response_model=PaperSearchResponse)
async def search_papers(
    search_request: PaperSearchRequest,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    """
    Search for papers across external APIs (PubMed, OpenAlex)

    Args:
        search_request: Search parameters
        current_user: Current authenticated user
        db: Database session

    Returns:
        Combined search results from requested sources
    """
    all_results: List[PaperSearchResult] = []
    sources = all_sources()
    for source in search_request.sources:
        service = sources.get(source.value)
        if service is None:
            continue
        try:
            all_results.extend(await service.search(
                search_request.query, search_request.max_results,
                search_request.start_year, search_request.end_year))
        except Exception as e:
            logger.warning(f"{source.value} search failed: {e}")

    return PaperSearchResponse(
        query=search_request.query,
        total_results=len(all_results),
        papers=all_results
    )


@router.post("/ingest", response_model=SessionPaperResponse)
async def ingest_paper_from_search(
    ingest_request: PaperIngestRequest,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    """
    Ingest a paper from search results into a session

    Args:
        ingest_request: Paper ingestion details
        current_user: Current authenticated user
        db: Database session

    Returns:
        Created session paper object
    """
    # Check session permission
    session = check_session_permission(ingest_request.session_id, current_user, db, EDIT_ROLES)

    # Check if paper already exists in database
    existing_paper = db.query(Paper).filter(
        Paper.source == ingest_request.source,
        Paper.source_id == ingest_request.source_id
    ).first()

    if existing_paper:
        # Check if already added to this session
        existing_session_paper = db.query(SessionPaper).filter(
            SessionPaper.session_id == ingest_request.session_id,
            SessionPaper.paper_id == existing_paper.id
        ).first()

        if existing_session_paper:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Paper already added to this session"
            )

        paper = existing_paper
    else:
        # Fetch paper details from source
        paper_data = None

        if ingest_request.source == PaperSource.PUBMED:
            pubmed_service = PubMedService()
            # Re-fetch to get latest data
            results = await pubmed_service._fetch_paper_details([ingest_request.source_id])
            if results:
                paper_data = results[0]

        elif ingest_request.source == PaperSource.OPENALEX:
            openalex_service = OpenAlexService()
            work = await openalex_service.get_paper_details(ingest_request.source_id)
            if work:
                paper_data = openalex_service._parse_openalex_work(work)

        elif ingest_request.source in (PaperSource.SEMANTIC_SCHOLAR, PaperSource.ARXIV):
            service = all_sources()[ingest_request.source.value]
            paper_data = await service.get_by_id(ingest_request.source_id)

        if not paper_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Paper not found in source API"
            )

        # Create paper in database
        paper = Paper(
            title=paper_data.title,
            abstract=paper_data.abstract,
            authors=paper_data.authors,
            publication_date=parse_date(paper_data.publication_date),
            journal=paper_data.journal,
            doi=paper_data.doi,
            source=paper_data.source,
            source_id=paper_data.source_id,
            url=paper_data.url,
            citations_count=paper_data.citations_count or 0
        )

        db.add(paper)
        db.commit()
        db.refresh(paper)

    # Embeddings are per session (by design), so embed even when the paper
    # already exists in the database from another session.
    vector_store = VectorStoreService(db)
    if not vector_store.has_embeddings(ingest_request.session_id, paper.id):
        try:
            embedding_service = EmbeddingService()
            chunks, embeddings = await embedding_service.embed_paper(
                title=paper.title,
                abstract=paper.abstract or "",
                full_text=paper.full_text,
            )
            if chunks and embeddings:
                await vector_store.add_paper_embeddings(
                    session_id=ingest_request.session_id,
                    paper_id=paper.id,
                    chunks=chunks,
                    embeddings=embeddings,
                )
                paper.embedding_generated = True
                paper.embedding_model = settings.EMBEDDING_MODEL
                db.commit()
        except Exception as e:
            logger.error(f"Error generating embeddings for paper {paper.id}: {e}")
            # Continue even if embedding fails

    # Add to session
    session_paper = SessionPaper(
        session_id=ingest_request.session_id,
        paper_id=paper.id,
        added_by_user_id=current_user.id
    )

    db.add(session_paper)
    db.commit()
    db.refresh(session_paper)

    return session_paper


@router.post("/upload/{session_id}", response_model=PaperUploadResponse)
async def upload_paper(
    session_id: int,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    authors: Optional[str] = Form(None),
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    """
    Upload a paper file (PDF or DOCX) to a session

    Args:
        session_id: Session ID to add paper to
        file: Uploaded file
        title: Optional paper title
        authors: Optional comma-separated authors
        current_user: Current authenticated user
        db: Database session

    Returns:
        Upload response with paper and session paper IDs
    """
    # Check session permission
    session = check_session_permission(session_id, current_user, db, EDIT_ROLES)

    # Validate file type
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided"
        )

    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in ['.pdf', '.docx', '.doc']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF and DOCX files are supported"
        )

    # Save file
    upload_dir = os.path.join(settings.UPLOAD_DIR, f"session_{session_id}")
    os.makedirs(upload_dir, exist_ok=True)

    # Generate unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_filename = f"{timestamp}_{file.filename}"
    file_path = os.path.join(upload_dir, safe_filename)

    # Write file
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Extract text and metadata
    try:
        extraction_result = TextExtractor.extract_from_file(file_path)
        full_text = extraction_result["full_text"]
        file_metadata = extraction_result["metadata"]

        # Use provided title or extract from file
        paper_title = title or file_metadata.get("title") or file.filename

        # Parse authors if provided
        author_list = None
        if authors:
            author_list = [a.strip() for a in authors.split(",")]
        elif file_metadata.get("author"):
            author_list = [file_metadata["author"]]

    except Exception as e:
        logger.error(f"Error extracting text from uploaded file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing file: {str(e)}"
        )

    # Create paper in database
    paper = Paper(
        title=paper_title,
        abstract=None,
        authors=author_list,
        source=PaperSource.MANUAL_UPLOAD,
        full_text=full_text,
        file_path=file_path
    )

    db.add(paper)
    db.commit()
    db.refresh(paper)

    # Generate embeddings
    try:
        embedding_service = EmbeddingService()
        vector_store = VectorStoreService(db)

        chunks, embeddings = await embedding_service.embed_paper(
            title=paper.title,
            abstract=paper.abstract or "",
            full_text=full_text
        )

        if chunks and embeddings:
            await vector_store.add_paper_embeddings(
                session_id=session_id,
                paper_id=paper.id,
                chunks=chunks,
                embeddings=embeddings,
                metadata={
                    "title": paper.title,
                    "source": paper.source.value,
                    "file_path": file_path
                }
            )

            paper.embedding_generated = True
            paper.embedding_model = settings.EMBEDDING_MODEL
            db.commit()

    except Exception as e:
        logger.error(f"Error generating embeddings for uploaded paper: {e}")
        # Continue even if embedding fails

    # Add to session
    session_paper = SessionPaper(
        session_id=session_id,
        paper_id=paper.id,
        added_by_user_id=current_user.id
    )

    db.add(session_paper)
    db.commit()
    db.refresh(session_paper)

    return PaperUploadResponse(
        paper_id=paper.id,
        session_paper_id=session_paper.id,
        message="Paper uploaded and added to session successfully",
        file_path=file_path
    )


@router.get("/sessions/{session_id}/papers", response_model=List[SessionPaperResponse])
def list_session_papers(
    session_id: int,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    """
    List all papers in a session

    Args:
        session_id: Session ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List of session papers with details
    """
    # Check session permission
    check_session_permission(session_id, current_user, db)

    # Get session papers
    session_papers = db.query(SessionPaper).filter(
        SessionPaper.session_id == session_id
    ).all()

    return session_papers


@router.get("/papers/{paper_id}", response_model=PaperResponse)
def get_paper(
    paper_id: int,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    """
    Get paper details

    Args:
        paper_id: Paper ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        Paper details
    """
    paper = db.query(Paper).filter(Paper.id == paper_id).first()

    if not paper:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paper not found"
        )

    return paper


@router.put("/sessions/{session_id}/papers/{paper_id}", response_model=SessionPaperResponse)
def update_session_paper(
    session_id: int,
    paper_id: int,
    update_data: SessionPaperUpdate,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    """
    Update session paper (notes, relevance score)

    Args:
        session_id: Session ID
        paper_id: Paper ID
        update_data: Update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Updated session paper
    """
    # Check session permission
    check_session_permission(session_id, current_user, db, EDIT_ROLES)

    # Get session paper
    session_paper = db.query(SessionPaper).filter(
        SessionPaper.session_id == session_id,
        SessionPaper.paper_id == paper_id
    ).first()

    if not session_paper:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paper not found in session"
        )

    # Update fields
    if update_data.notes is not None:
        session_paper.notes = update_data.notes
    if update_data.relevance_score is not None:
        session_paper.relevance_score = update_data.relevance_score

    db.commit()
    db.refresh(session_paper)

    return session_paper


@router.delete("/sessions/{session_id}/papers/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_paper_from_session(
    session_id: int,
    paper_id: int,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    """
    Remove a paper from a session

    Args:
        session_id: Session ID
        paper_id: Paper ID
        current_user: Current authenticated user
        db: Database session
    """
    # Check session permission
    check_session_permission(session_id, current_user, db, EDIT_ROLES)

    # Get session paper
    session_paper = db.query(SessionPaper).filter(
        SessionPaper.session_id == session_id,
        SessionPaper.paper_id == paper_id
    ).first()

    if not session_paper:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paper not found in session"
        )

    # Remove from vector store
    try:
        vector_store = VectorStoreService(db)
        await vector_store.delete_paper_embeddings(session_id, paper_id)
    except Exception as e:
        logger.error(f"Error deleting embeddings: {e}")
        # Continue even if vector deletion fails

    # Delete session paper
    db.delete(session_paper)
    db.commit()
