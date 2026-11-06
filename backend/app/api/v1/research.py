"""
Research POC endpoints: discovery, themes, gaps, chat, upload, export, sharing.
The Streamlit UI calls the same services directly; these expose them over HTTP.
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.api.deps import get_current_active_user
from app.core.database import get_db
from app.models.research import SessionMessage
from app.models.session import Session
from app.models.user import User
from app.services import access
from app.services.analysis_service import generate_gaps, generate_themes
from app.services.chat_service import answer_question
from app.services.discovery_service import discover_papers, get_artifact, source_status
from app.services.export_service import STYLES, draft_review, render
from app.services.upload_service import UploadError, add_uploaded_paper

router = APIRouter()


def _session(db: DBSession, session_id: int, user: User, edit: bool = False) -> Session:
    s = db.query(Session).filter(Session.id == session_id).first()
    if not s or not access.can_view(db, s, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    if edit and not access.can_edit(db, s, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You have read-only access to this session")
    return s


class DiscoverRequest(BaseModel):
    topic: Optional[str] = Field(None, description="Defaults to the session topic")
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    max_papers: Optional[int] = Field(None, ge=5, le=100)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=2)


class ExportRequest(BaseModel):
    style: str = "APA"
    format: str = Field("docx", pattern="^(docx|pdf)$")
    regenerate: bool = False


class ShareRequest(BaseModel):
    email: str
    role: str = Field("viewer", pattern="^(viewer|contributor)$")


@router.get("/sources")
def get_sources(current_user: User = Depends(get_current_active_user)):
    """Which paper sources are in full vs limited mode."""
    return source_status()


@router.post("/sessions/{session_id}/discover")
async def discover(session_id: int, req: DiscoverRequest,
                   current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    topic = req.topic or s.topic or s.title
    return await discover_papers(db, s.id, current_user.id, topic, req.start_year, req.end_year, req.max_papers)


@router.post("/sessions/{session_id}/themes")
async def themes(session_id: int, current_user: User = Depends(get_current_active_user),
                 db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    return await generate_themes(db, s.id, s.topic or s.title)


@router.post("/sessions/{session_id}/gaps")
async def gaps(session_id: int, current_user: User = Depends(get_current_active_user),
               db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    return {"gaps": await generate_gaps(db, s.id, s.topic or s.title)}


@router.get("/sessions/{session_id}/analysis")
def analysis(session_id: int, current_user: User = Depends(get_current_active_user),
             db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user)
    return {"discovery": get_artifact(db, s.id, "discovery"), "analysis": get_artifact(db, s.id, "analysis")}


@router.post("/sessions/{session_id}/chat")
async def chat(session_id: int, req: ChatRequest, current_user: User = Depends(get_current_active_user),
               db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    return await answer_question(db, s.id, current_user.id, req.question)


@router.get("/sessions/{session_id}/messages")
def messages(session_id: int, current_user: User = Depends(get_current_active_user),
             db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user)
    rows = db.query(SessionMessage).filter(SessionMessage.session_id == s.id).order_by(SessionMessage.id).all()
    return [{"role": m.role, "content": m.content, "citations": m.citations,
             "created_at": m.created_at} for m in rows]


@router.post("/sessions/{session_id}/upload")
async def upload(session_id: int, file: UploadFile = File(...),
                 current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    try:
        paper = await add_uploaded_paper(db, s.id, current_user.id, file.filename or "upload.pdf", await file.read())
    except UploadError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return {"paper_id": paper.id, "title": paper.title}


@router.post("/sessions/{session_id}/export")
async def export(session_id: int, req: ExportRequest, current_user: User = Depends(get_current_active_user),
                 db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user)
    if req.style.upper() not in STYLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"style must be one of {STYLES}")
    review = get_artifact(db, s.id, "lit_review")
    if req.regenerate or not review:
        if not access.can_edit(db, s, current_user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only editors can generate a new review")
        review = await draft_review(db, s.id, s.topic or s.title)
    data = render(db, s.id, review, req.style, req.format)
    media = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"
             if req.format == "docx" else "application/pdf")
    return Response(data, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="literature-review-{s.id}.{req.format}"'})


@router.post("/sessions/{session_id}/share")
def share(session_id: int, req: ShareRequest, current_user: User = Depends(get_current_active_user),
          db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user)
    try:
        m = access.share_session(db, s, current_user, req.email, req.role)
    except access.AccessError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return {"session_id": s.id, "user_id": m.user_id, "role": m.role.value}
