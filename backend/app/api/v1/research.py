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
from app.services import gaps_service as gs
from app.services import writing_service as ws

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
    gap_id: Optional[int] = Field(None, description="Ask within a gap's own thread")


class GapCreate(BaseModel):
    title: str = Field(..., min_length=5)
    description: str = ""
    assess: bool = True


class GapUpdate(BaseModel):
    pinned: Optional[bool] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class SectionUpdate(BaseModel):
    user_text: str
    heading: Optional[str] = None


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
    gap = _gap(db, s, req.gap_id) if req.gap_id else None
    return await answer_question(db, s.id, current_user.id, req.question, gap=gap)


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


# ── Gaps workspace ───────────────────────────────────────────────────────────

def _gap(db: DBSession, s: Session, gap_id: int):
    g = gs.get_gap(db, gap_id)
    if not g or g.session_id != s.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gap not found")
    return g


def _gap_out(g) -> dict:
    return {"id": g.id, "title": g.title, "description": g.description, "gap_type": g.gap_type,
            "research_question": g.research_question, "confidence": g.confidence,
            "evidence_paper_ids": g.evidence_paper_ids or [], "source": g.source, "pinned": g.pinned,
            "status": g.status, "notes": g.notes, "assessment": g.assessment}


@router.get("/sessions/{session_id}/gaps")
def list_gaps(session_id: int, current_user: User = Depends(get_current_active_user),
              db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user)
    return [_gap_out(g) for g in gs.list_gaps(db, s.id)]


@router.post("/sessions/{session_id}/gaps/custom")
async def add_gap(session_id: int, req: GapCreate, current_user: User = Depends(get_current_active_user),
                  db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    try:
        g = gs.add_user_gap(db, s.id, current_user.id, req.title, req.description)
    except gs.GapError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    if req.assess:
        await gs.assess_gap(db, g)
    return _gap_out(g)


@router.patch("/sessions/{session_id}/gaps/{gap_id}")
def update_gap(session_id: int, gap_id: int, req: GapUpdate,
               current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    try:
        return _gap_out(gs.update_gap(db, _gap(db, s, gap_id), pinned=req.pinned, status=req.status,
                                      notes=req.notes))
    except gs.GapError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.post("/sessions/{session_id}/gaps/{gap_id}/assess")
async def assess_gap(session_id: int, gap_id: int, current_user: User = Depends(get_current_active_user),
                     db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    return _gap_out(await gs.assess_gap(db, _gap(db, s, gap_id)))


# ── Writing guide ────────────────────────────────────────────────────────────

def _section_out(x) -> dict:
    return {"id": x.id, "position": x.position, "heading": x.heading, "kind": x.kind,
            "guidance": x.guidance, "user_text": x.user_text, "feedback": x.feedback,
            "words": ws.word_count(x.user_text)}


def _section(db: DBSession, s: Session, section_id: int):
    from app.models.research import WritingSection
    x = db.get(WritingSection, section_id)
    if not x or x.session_id != s.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Section not found")
    return x


@router.get("/sessions/{session_id}/writing")
def get_writing(session_id: int, current_user: User = Depends(get_current_active_user),
                db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user)
    return {"title": ws.get_title(db, s.id, f"Literature review: {s.topic or s.title}"),
            "sections": [_section_out(x) for x in ws.list_sections(db, s.id)]}


@router.post("/sessions/{session_id}/writing/outline")
async def writing_outline(session_id: int, current_user: User = Depends(get_current_active_user),
                          db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    try:
        return [_section_out(x) for x in await ws.generate_outline(db, s.id, s.topic or s.title)]
    except ws.WritingError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.put("/sessions/{session_id}/writing/sections/{section_id}")
def save_section(session_id: int, section_id: int, req: SectionUpdate,
                 current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    return _section_out(ws.save_text(db, _section(db, s, section_id), req.user_text, current_user.id, req.heading))


@router.post("/sessions/{session_id}/writing/sections/{section_id}/check")
async def check_section(session_id: int, section_id: int,
                        current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    try:
        return await ws.check_section(db, _section(db, s, section_id))
    except ws.WritingError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("/sessions/{session_id}/writing/export")
def export_writing(session_id: int, style: str = "APA", format: str = "docx",
                   current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user)
    review = ws.compile_review(db, s.id, f"Literature review: {s.topic or s.title}")
    if not review["sections"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing written yet")
    if style.upper() not in STYLES or format not in ("docx", "pdf"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid style or format")
    data = render(db, s.id, review, style, format, user_written=True)
    media = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"
             if format == "docx" else "application/pdf")
    return Response(data, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="literature-review-{s.id}.{format}"'})
