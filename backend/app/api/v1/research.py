"""
Research POC endpoints: discovery, themes, gaps, chat, upload, export, sharing.
The React web app (frontend/) uses these endpoints.
"""
import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.api.deps import get_current_active_user
from app.core.database import SessionLocal, get_db
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
from app.services import triage_service as ts
from app.services import collab_service as cs

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
    theme: Optional[int] = Field(None, ge=0, description="Focus on this theme (index in the theme list)")
    section_id: Optional[int] = Field(None, description="Focus on this writing section")


class GapCreate(BaseModel):
    title: str = Field(..., min_length=5)
    description: str = ""
    assess: bool = True


class GapUpdate(BaseModel):
    pinned: Optional[bool] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    research_question: Optional[str] = Field(None, max_length=1000)


class SectionUpdate(BaseModel):
    user_text: str
    heading: Optional[str] = None
    base_version: Optional[int] = Field(None, description="The version you started editing; a newer one means a conflict")


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
    from app.services.links_service import THEMES_REFRESH_AFTER, basis, changes_since, describe
    s = _session(db, session_id, current_user)
    a = get_artifact(db, s.id, "analysis")
    ch = changes_since((a or {}).get("basis"), basis(db, s.id)) if a and a.get("themes") else None
    moved = (ch or {}).get("papers_added", 0) + (ch or {}).get("papers_removed", 0)
    return {"discovery": get_artifact(db, s.id, "discovery"), "analysis": a,
            "changes": {**ch, "summary": describe(ch)} if ch else None,
            "refresh_due": moved >= THEMES_REFRESH_AFTER}


@router.post("/sessions/{session_id}/chat")
async def chat(session_id: int, req: ChatRequest, current_user: User = Depends(get_current_active_user),
               db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    gap = _gap(db, s, req.gap_id) if req.gap_id else None
    return await answer_question(db, s.id, current_user.id, req.question, gap=gap)


@router.get("/sessions/{session_id}/messages")
def messages(session_id: int, gap_id: Optional[int] = None,
             current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user)
    thread = SessionMessage.gap_id.is_(None) if gap_id is None else SessionMessage.gap_id == gap_id
    rows = (db.query(SessionMessage).filter(SessionMessage.session_id == s.id, thread)
            .order_by(SessionMessage.id).all())
    return [{"role": m.role, "content": m.content, "citations": m.citations,
             "created_at": m.created_at} for m in rows]


@router.post("/sessions/{session_id}/upload")
async def upload(session_id: int, file: UploadFile = File(...), attach_to: Optional[int] = None,
                 current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    """Upload a PDF/DOCX. A copy of a paper already in the session (or the one named by
    `attach_to`) becomes that paper's full text instead of a new paper."""
    s = _session(db, session_id, current_user, edit=True)
    try:
        paper = await add_uploaded_paper(db, s.id, current_user.id, file.filename or "upload.pdf",
                                         await file.read(), attach_to=attach_to)
    except (UploadError, ts.TriageError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    attached = bool(getattr(paper, "attached", False))
    n = ts.get_link(db, s.id, paper.id).ref_no
    cs.log(db, s.id, current_user.id, "paper_full_text" if attached else "paper_added",
           f"uploaded the PDF of paper {n}" if attached else f"added paper {n} from a PDF", "paper", paper.id)
    return {"paper_id": paper.id, "title": paper.title, "attached": attached}


class PaperUpdate(BaseModel):
    status: Optional[str] = None
    is_key: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=4000)
    removed_reason: Optional[str] = None


class DoiBody(BaseModel):
    doi: str = Field(..., min_length=6, max_length=300)


@router.patch("/sessions/{session_id}/papers/{paper_id}")
def update_paper(session_id: int, paper_id: int, body: PaperUpdate,
                 current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    """Keep or remove a paper, mark it as a key paper, or edit its note."""
    s = _session(db, session_id, current_user, edit=True)
    try:
        sp = ts.get_link(db, s.id, paper_id)
        if body.status is not None and body.status != sp.status:
            # Removing or restoring a paper is a big change: a proposal when others can edit too.
            kind = "remove_paper" if body.status == "removed" else "restore_paper"
            if body.status not in ts.STATUSES:
                raise ts.TriageError("Status must be 'kept' or 'removed'.")
            prop = cs.change_or_propose(db, s, current_user, kind, paper_id,
                                        {"reason": body.removed_reason} if body.removed_reason else None)
            if prop is not None:
                return JSONResponse(status_code=202, content=jsonable_encoder(
                    {"proposal": cs.proposal_out(db, prop), "paper": _paper_out(db, s.id, paper_id)}))
        elif body.removed_reason is not None:
            ts.update_paper(db, s.id, paper_id, current_user.id, removed_reason=body.removed_reason)
        if body.is_key is not None and body.is_key != sp.is_key:
            ts.update_paper(db, s.id, paper_id, current_user.id, is_key=body.is_key)
            cs.log(db, s.id, current_user.id, "paper_key" if body.is_key else "paper_unkey",
                   f"{'marked' if body.is_key else 'unmarked'} paper {sp.ref_no} as a key paper", "paper", paper_id)
        if body.notes is not None:
            ts.update_paper(db, s.id, paper_id, current_user.id, notes=body.notes)
            cs.log(db, s.id, current_user.id, "paper_note", f"edited the note on paper {sp.ref_no}", "paper", paper_id)
    except ts.TriageError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except cs.CollabError as e:
        raise _collab_http(e)
    return _paper_out(db, s.id, paper_id)


@router.post("/sessions/{session_id}/papers/doi", status_code=201)
async def add_by_doi(session_id: int, body: DoiBody,
                     current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    from app.services.discovery_service import AddPaperError, add_paper_by_doi
    s = _session(db, session_id, current_user, edit=True)
    try:
        paper = await add_paper_by_doi(db, s.id, current_user.id, body.doi)
    except AddPaperError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    out = _paper_out(db, s.id, paper.id)
    cs.log(db, s.id, current_user.id, "paper_added", f"added paper {out['n']} by DOI", "paper", paper.id)
    return out


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
            "status": g.status, "notes": g.notes, "assessment": g.assessment, "created_by": g.created_by}


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
    cs.log(db, s.id, current_user.id, "gap_added", f"added a gap: \"{g.title}\"", "gap", g.id)
    if req.assess:
        await gs.assess_gap(db, g)
    return _gap_out(g)


@router.patch("/sessions/{session_id}/gaps/{gap_id}")
def update_gap(session_id: int, gap_id: int, req: GapUpdate,
               current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    g = _gap(db, s, gap_id)
    try:
        if req.pinned is False and g.pinned:
            prop = cs.change_or_propose(db, s, current_user, "untrack_gap", g.id)
            if prop is not None:
                return JSONResponse(status_code=202, content=jsonable_encoder(
                    {"proposal": cs.proposal_out(db, prop), "gap": _gap_out(g)}))
        elif req.pinned is True and not g.pinned:
            gs.update_gap(db, g, pinned=True)
            cs.log(db, s.id, current_user.id, "gap_tracked", f"tracked gap \"{g.title}\"", "gap", g.id)
        if req.status is not None and req.status != g.status:
            gs.update_gap(db, g, status=req.status)
            cs.log(db, s.id, current_user.id, "gap_status", f"marked gap \"{g.title}\" as {req.status}", "gap", g.id)
        if req.notes is not None or req.research_question is not None:
            gs.update_gap(db, g, notes=req.notes, research_question=req.research_question)
            cs.log(db, s.id, current_user.id, "gap_note", f"edited notes on gap \"{g.title}\"", "gap", g.id)
        return _gap_out(g)
    except gs.GapError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except cs.CollabError as e:
        raise _collab_http(e)


@router.post("/sessions/{session_id}/gaps/{gap_id}/assess")
async def assess_gap(session_id: int, gap_id: int, current_user: User = Depends(get_current_active_user),
                     db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    g = await gs.assess_gap(db, _gap(db, s, gap_id))
    verdict = ((g.assessment or {}).get("novelty") or {}).get("verdict", "unknown").replace("_", " ")
    cs.log(db, s.id, current_user.id, "gap_checked", f"checked gap \"{g.title}\": {verdict}", "gap", g.id)
    return _gap_out(g)


# ── Writing guide ────────────────────────────────────────────────────────────

def _section_out(x, db: Optional[DBSession] = None) -> dict:
    return {"id": x.id, "position": x.position, "heading": x.heading, "kind": x.kind,
            "guidance": x.guidance, "user_text": x.user_text, "feedback": x.feedback,
            "words": ws.word_count(x.user_text), "owner_id": x.owner_id, "version": x.version or 0,
            "updated_by": x.updated_by, "updated_at": x.updated_at}


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
            "sections": [_section_out(x) for x in ws.list_sections(db, s.id)],
            "guide_changes": ws.guidance_changes(db, s.id)}


@router.post("/sessions/{session_id}/writing/guidance/refresh")
async def refresh_guidance(session_id: int, current_user: User = Depends(get_current_active_user),
                           db: DBSession = Depends(get_db)):
    """Update the guide's suggestions for the current outline. Never changes the user's text."""
    from app.services.links_service import describe
    s = _session(db, session_id, current_user, edit=True)
    try:
        ch = await ws.refresh_guidance(db, s.id, s.topic or s.title)
    except ws.WritingError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return {"summary": describe(ch) if ch else "", "sections": [_section_out(x) for x in ws.list_sections(db, s.id)]}


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
    try:
        x = cs.save_section_text(db, s, current_user, _section(db, s, section_id), req.user_text, req.heading,
                                 req.base_version)
    except cs.CollabError as e:
        raise _collab_http(e)
    return _section_out(x, db)


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


# ── Web app: sessions, papers, members, streaming ────────────────────────────

class SessionCreateBody(BaseModel):
    topic: str = Field(..., min_length=5, max_length=2000)
    title: Optional[str] = Field(None, max_length=120)


class TitleBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)


class SectionCreate(BaseModel):
    heading: str = Field(..., min_length=1, max_length=300)


class MoveBody(BaseModel):
    direction: int = Field(..., ge=-1, le=1)


def _session_out(db: DBSession, s: Session, user: User) -> dict:
    from app.models.paper import SessionPaper
    from app.models.research import Gap
    role = access.role_of(db, s, user)
    analysis = get_artifact(db, s.id, "analysis") or {}
    return {"id": s.id, "title": s.title, "topic": s.topic, "role": role,
            "can_edit": access.can_edit(db, s, user), "can_manage": access.can_manage(db, s, user),
            "paper_count": db.query(SessionPaper).filter(SessionPaper.session_id == s.id,
                                                         SessionPaper.status == "kept").count(),
            "theme_count": len(analysis.get("themes") or []),
            "gap_count": db.query(Gap).filter(Gap.session_id == s.id).count(),
            "words": sum(ws.word_count(x.user_text) for x in ws.list_sections(db, s.id)),
            "created_at": s.created_at, "updated_at": s.updated_at}


@router.get("/sessions")
def my_sessions(current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    return [_session_out(db, s, current_user) for s in access.list_user_sessions(db, current_user)]


@router.post("/sessions", status_code=201)
def create_session(body: SessionCreateBody, current_user: User = Depends(get_current_active_user),
                   db: DBSession = Depends(get_db)):
    topic = body.topic.strip()
    s = Session(title=(body.title or topic)[:120], topic=topic, creator_id=current_user.id)
    db.add(s)
    db.commit()
    return _session_out(db, s, current_user)


@router.get("/sessions/{session_id}")
def session_detail(session_id: int, current_user: User = Depends(get_current_active_user),
                   db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user)
    out = _session_out(db, s, current_user)
    out["discovery"] = get_artifact(db, s.id, "discovery")
    out["screening"] = ts.screening_summary(db, s.id, (out["discovery"] or {}).get("candidates"))
    return out


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: int, current_user: User = Depends(get_current_active_user),
                   db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user)
    if s.creator_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can delete a session")
    db.delete(s)
    db.commit()
    return Response(status_code=204)


@router.get("/sessions/{session_id}/papers")
def session_papers(session_id: int, current_user: User = Depends(get_current_active_user),
                   db: DBSession = Depends(get_db)):
    from app.services.analysis_service import list_session_papers
    s = _session(db, session_id, current_user)
    return [_paper_dict(p) for p in list_session_papers(db, s.id, include_removed=True)]


def _paper_dict(p) -> dict:
    sp = p.session_link
    extra = p.extra_metadata or {}
    return {"id": p.id, "n": p.session_ref, "title": p.title, "authors": p.authors or [],
            "year": p.publication_date.year if p.publication_date else None, "journal": p.journal,
            "doi": p.doi, "url": p.url or (f"https://doi.org/{p.doi}" if p.doi else None),
            "abstract": p.abstract, "citations": p.citations_count or 0,
            "found_in": extra.get("found_in") or [p.source.value],
            "uploaded": bool(extra.get("uploaded")),
            "status": sp.status, "is_key": bool(sp.is_key), "notes": sp.notes,
            "removed_reason": sp.removed_reason,
            "full_text": bool(p.full_text), "full_text_source": extra.get("full_text_source")
                         or ("upload" if extra.get("uploaded") and p.full_text else None),
            "added_at": sp.added_at, "added_by": sp.added_by_user_id, "status_by": sp.status_by_user_id}


def _paper_out(db: DBSession, session_id: int, paper_id: int) -> dict:
    from app.services.analysis_service import list_session_papers
    for p in list_session_papers(db, session_id, include_removed=True):
        if p.id == paper_id:
            return _paper_dict(p)
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Paper not found")


@router.get("/sessions/{session_id}/members")
def members(session_id: int, current_user: User = Depends(get_current_active_user),
            db: DBSession = Depends(get_db)):
    from app.models.session import SessionMember
    s = _session(db, session_id, current_user)
    owner = db.get(User, s.creator_id)
    out = [{"user_id": owner.id, "email": owner.email, "full_name": owner.full_name, "role": "owner"}]
    for m in db.query(SessionMember).filter(SessionMember.session_id == s.id).all():
        u = db.get(User, m.user_id)
        out.append({"user_id": u.id, "email": u.email, "full_name": u.full_name, "role": m.role.value})
    return out


@router.delete("/sessions/{session_id}/members/{user_id}", status_code=204)
def remove_member(session_id: int, user_id: int, current_user: User = Depends(get_current_active_user),
                  db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user)
    try:
        access.unshare_session(db, s, current_user, user_id)
    except access.AccessError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    return Response(status_code=204)


@router.delete("/sessions/{session_id}/gaps/{gap_id}", status_code=204)
def delete_gap(session_id: int, gap_id: int, current_user: User = Depends(get_current_active_user),
               db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    try:
        prop = cs.change_or_propose(db, s, current_user, "delete_gap", _gap(db, s, gap_id).id)
    except cs.CollabError as e:
        raise _collab_http(e)
    if prop is not None:
        return JSONResponse(status_code=202, content=jsonable_encoder({"proposal": cs.proposal_out(db, prop)}))
    return Response(status_code=204)


@router.post("/sessions/{session_id}/writing/sections", status_code=201)
def add_section(session_id: int, body: SectionCreate, current_user: User = Depends(get_current_active_user),
                db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    try:
        x = ws.add_section(db, s.id, body.heading)
        x.owner_id = current_user.id
        db.commit()
        cs.log(db, s.id, current_user.id, "section_added", f"added section \"{x.heading}\"", "section", x.id)
        return _section_out(x, db)
    except ws.WritingError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.delete("/sessions/{session_id}/writing/sections/{section_id}", status_code=204)
def delete_section(session_id: int, section_id: int, current_user: User = Depends(get_current_active_user),
                   db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    try:
        prop = cs.change_or_propose(db, s, current_user, "delete_section", _section(db, s, section_id).id)
    except cs.CollabError as e:
        raise _collab_http(e)
    if prop is not None:
        return JSONResponse(status_code=202, content=jsonable_encoder({"proposal": cs.proposal_out(db, prop)}))
    return Response(status_code=204)


@router.post("/sessions/{session_id}/writing/sections/{section_id}/move")
def move_section(session_id: int, section_id: int, body: MoveBody,
                 current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    ws.move_section(db, _section(db, s, section_id), body.direction)
    return [_section_out(x) for x in ws.list_sections(db, s.id)]


@router.put("/sessions/{session_id}/writing/title")
def set_title(session_id: int, body: TitleBody, current_user: User = Depends(get_current_active_user),
              db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    ws.set_title(db, s.id, body.title)
    return {"title": body.title.strip()}


@router.get("/sessions/{session_id}/writing/example")
def get_example(session_id: int, style: str = "APA", current_user: User = Depends(get_current_active_user),
                db: DBSession = Depends(get_db)):
    from app.services.analysis_service import list_session_papers
    from app.services.export_service import format_review
    s = _session(db, session_id, current_user)
    review = get_artifact(db, s.id, "lit_review")
    return format_review(review, list_session_papers(db, s.id, include_removed=True), style) if review else None


@router.post("/sessions/{session_id}/writing/example")
async def make_example(session_id: int, current_user: User = Depends(get_current_active_user),
                       db: DBSession = Depends(get_db)):
    from app.services.analysis_service import list_session_papers
    from app.services.export_service import format_review
    s = _session(db, session_id, current_user, edit=True)
    review = await draft_review(db, s.id, s.topic or s.title)
    return format_review(review, list_session_papers(db, s.id, include_removed=True), "APA")


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.post("/sessions/{session_id}/analyse/stream")
async def analyse_stream(session_id: int, req: DiscoverRequest,
                         current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    """Find papers, then themes, then gaps, streaming progress as server-sent events."""
    s = _session(db, session_id, current_user, edit=True)
    sid, uid, topic = s.id, current_user.id, req.topic or s.topic or s.title

    async def events():
        queue: asyncio.Queue = asyncio.Queue()
        say = lambda m: queue.put_nowait({"type": "progress", "message": m})  # noqa: E731

        async def job():
            jdb = SessionLocal()
            try:
                stats = await discover_papers(jdb, sid, uid, topic, req.start_year, req.end_year,
                                              req.max_papers, progress=say)
                if stats.get("error"):
                    queue.put_nowait({"type": "error", "message": stats["error"]})
                    return
                cs.log(jdb, sid, uid, "papers_found", f"found {stats.get('added', 0)} new papers", "session", sid)
                say("Finding themes…")
                await generate_themes(jdb, sid, topic)
                say("Looking for research gaps…")
                await generate_gaps(jdb, sid, topic)
                queue.put_nowait({"type": "done", "stats": stats})
            except Exception as e:  # surface failures to the UI instead of hanging
                queue.put_nowait({"type": "error", "message": f"Analysis failed: {e}"})
            finally:
                jdb.close()

        task = asyncio.create_task(job())
        while True:
            item = await queue.get()
            yield _sse(item)
            if item["type"] in ("done", "error"):
                break
        await task

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)


def _focus(db: DBSession, s: Session, req: ChatRequest) -> Optional[dict]:
    """What the research partner panel is 'about': a theme or a writing section."""
    from app.models.research import WritingSection
    if req.theme is not None:
        themes = (get_artifact(db, s.id, "analysis") or {}).get("themes") or []
        if req.theme >= len(themes):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Theme not found")
        t = themes[req.theme]
        return {"kind": "theme", "label": t["label"], "paper_ids": t.get("paper_ids") or []}
    if req.section_id is not None:
        sec = db.get(WritingSection, req.section_id)
        if not sec or sec.session_id != s.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Section not found")
        return {"kind": "section", "heading": sec.heading, "text": sec.user_text or ""}
    return None


@router.get("/sessions/{session_id}/partner/notices")
def partner_notices(session_id: int, current_user: User = Depends(get_current_active_user),
                    db: DBSession = Depends(get_db)):
    from app.services.partner_service import notices
    s = _session(db, session_id, current_user)
    return notices(db, s.id)


@router.post("/sessions/{session_id}/chat/stream")
async def chat_stream(session_id: int, req: ChatRequest, current_user: User = Depends(get_current_active_user),
                      db: DBSession = Depends(get_db)):
    """Stream an answer token by token, then the citation-checked final answer."""
    from app.services.chat_service import build_context, save_exchange, stream_answer
    s = _session(db, session_id, current_user, edit=True)
    if req.gap_id:
        _gap(db, s, req.gap_id)
    focus = _focus(db, s, req)
    sid, uid, gap_id, question = s.id, current_user.id, req.gap_id, req.question

    async def events():
        cdb = SessionLocal()
        try:
            gap = gs.get_gap(cdb, gap_id) if gap_id else None
            ctx = await build_context(cdb, sid, question, gap=gap, focus=focus)
            parts = []
            async for piece in stream_answer(ctx):
                parts.append(piece)
                yield _sse({"type": "token", "text": piece})
            result = save_exchange(cdb, sid, uid, ctx, "".join(parts))
            yield _sse({"type": "done", **result})
        except Exception as e:
            yield _sse({"type": "error", "message": f"Chat failed: {e}"})
        finally:
            cdb.close()

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)


# ── Working together ──────────────────────────────────────────────────────────

def _collab_http(e: "cs.CollabError") -> HTTPException:
    detail = str(e) if not e.data else {"message": str(e), **e.data}
    return HTTPException(e.status, detail)


class ProposalBody(BaseModel):
    kind: str
    target_id: int
    reason: Optional[str] = None          # paper removal reason code
    reason_text: Optional[str] = Field(None, max_length=1000)


class DecisionBody(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject|withdraw|accept)$")


class CommentBody(BaseModel):
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    body: str = Field(..., min_length=1, max_length=4000)
    quote: Optional[str] = Field(None, max_length=500)
    parent_id: Optional[int] = None


class ResolveBody(BaseModel):
    resolved: bool = True


class SuggestionBody(BaseModel):
    text: str = Field(..., max_length=60000)
    note: Optional[str] = Field(None, max_length=1000)


class PresenceBody(BaseModel):
    where: str = Field("", max_length=80)


@router.get("/sessions/{session_id}/collab")
def collab_state(session_id: int, current_user: User = Depends(get_current_active_user),
                 db: DBSession = Depends(get_db)):
    """Who's in the session, whether proposals apply, and what's waiting for a decision."""
    s = _session(db, session_id, current_user)
    return {"members": cs.members(db, s), "collaborative": cs.is_collaborative(db, s), "me": current_user.id,
            "proposals": [cs.proposal_out(db, p) for p in cs.pending_proposals(db, s.id)],
            "suggestions": [cs.suggestion_out(db, x) for x in cs.pending_suggestions(db, s.id)],
            "present": cs.present(db, s.id, current_user.id)}


@router.post("/sessions/{session_id}/proposals", status_code=201)
def create_proposal(session_id: int, body: ProposalBody, current_user: User = Depends(get_current_active_user),
                    db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    try:
        p = cs.propose(db, s, current_user, body.kind, body.target_id,
                       {"reason": body.reason} if body.reason else None, body.reason_text)
    except cs.CollabError as e:
        raise _collab_http(e)
    return cs.proposal_out(db, p)


@router.post("/sessions/{session_id}/proposals/{proposal_id}/decide")
def decide_proposal(session_id: int, proposal_id: int, body: DecisionBody,
                    current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    try:
        p = cs.decide(db, s, current_user, proposal_id, body.decision)
    except (cs.CollabError, ts.TriageError) as e:
        raise _collab_http(e) if isinstance(e, cs.CollabError) else HTTPException(400, str(e))
    return cs.proposal_out(db, p)


@router.get("/sessions/{session_id}/comments")
def list_comments(session_id: int, target_type: Optional[str] = None, target_id: Optional[int] = None,
                  current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user)
    return cs.threads(db, s.id, target_type, target_id)


@router.post("/sessions/{session_id}/comments", status_code=201)
def add_comment(session_id: int, body: CommentBody, current_user: User = Depends(get_current_active_user),
                db: DBSession = Depends(get_db)):
    """Anyone with access can comment, viewers included (e.g. a supervisor)."""
    s = _session(db, session_id, current_user)
    try:
        c = cs.add_comment(db, s, current_user, body.target_type or "", body.target_id or 0, body.body,
                           body.quote, body.parent_id)
    except cs.CollabError as e:
        raise _collab_http(e)
    return {"id": c.id}


@router.post("/sessions/{session_id}/comments/{comment_id}/resolve")
def resolve_comment(session_id: int, comment_id: int, body: ResolveBody,
                    current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user)
    try:
        c = cs.resolve_comment(db, s, current_user, comment_id, body.resolved)
    except cs.CollabError as e:
        raise _collab_http(e)
    return {"id": c.id, "resolved": c.resolved}


@router.get("/sessions/{session_id}/suggestions")
def list_suggestions(session_id: int, section_id: Optional[int] = None,
                     current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user)
    return [cs.suggestion_out(db, x) for x in cs.pending_suggestions(db, s.id, section_id)]


@router.post("/sessions/{session_id}/writing/sections/{section_id}/suggestions", status_code=201)
def suggest_edit(session_id: int, section_id: int, body: SuggestionBody,
                 current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    try:
        x = cs.suggest_edit(db, s, current_user, _section(db, s, section_id), body.text, body.note)
    except cs.CollabError as e:
        raise _collab_http(e)
    return cs.suggestion_out(db, x)


@router.post("/sessions/{session_id}/suggestions/{suggestion_id}/decide")
def decide_suggestion(session_id: int, suggestion_id: int, body: DecisionBody,
                      current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user, edit=True)
    try:
        x = cs.decide_suggestion(db, s, current_user, suggestion_id, body.decision)
    except cs.CollabError as e:
        raise _collab_http(e)
    return cs.suggestion_out(db, x)


@router.get("/sessions/{session_id}/whats-new")
def whats_new(session_id: int, current_user: User = Depends(get_current_active_user),
              db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user)
    return cs.whats_new(db, s, current_user)


@router.post("/sessions/{session_id}/seen", status_code=204)
def mark_seen(session_id: int, current_user: User = Depends(get_current_active_user),
              db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user)
    cs.mark_seen(db, s, current_user)
    return Response(status_code=204)


@router.get("/sessions/{session_id}/history")
def history(session_id: int, target_type: str, target_id: int,
            current_user: User = Depends(get_current_active_user), db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user)
    return cs.history(db, s.id, target_type, target_id)


@router.post("/sessions/{session_id}/presence")
def presence(session_id: int, body: PresenceBody, current_user: User = Depends(get_current_active_user),
             db: DBSession = Depends(get_db)):
    s = _session(db, session_id, current_user)
    cs.heartbeat(s.id, current_user.id, body.where)
    return cs.present(db, s.id, current_user.id)
