"""
Paper triage: keep or remove a paper, mark key papers, keep notes.

Removed papers stay in the session (with their fixed citation number) but are
left out of themes, gaps, chat, the writing guide and suggestions. Nothing is
ever deleted, so every removal can be undone.
"""
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.models.paper import SessionPaper

REASONS = ("off_topic", "wrong_population", "wrong_study_type", "not_peer_reviewed", "duplicate", "other")
STATUSES = ("kept", "removed")


class TriageError(Exception):
    pass


def next_ref_no(db: DBSession, session_id: int) -> int:
    top = db.query(func.max(SessionPaper.ref_no)).filter(SessionPaper.session_id == session_id).scalar()
    return (top or 0) + 1


def get_link(db: DBSession, session_id: int, paper_id: int) -> SessionPaper:
    sp = (db.query(SessionPaper)
          .filter(SessionPaper.session_id == session_id, SessionPaper.paper_id == paper_id).first())
    if sp is None:
        raise TriageError("That paper is not in this session.")
    return sp


def update_paper(db: DBSession, session_id: int, paper_id: int, user_id: int, *,
                 status: Optional[str] = None, is_key: Optional[bool] = None,
                 notes: Optional[str] = None, removed_reason: Optional[str] = None) -> SessionPaper:
    sp = get_link(db, session_id, paper_id)
    if status is not None:
        if status not in STATUSES:
            raise TriageError("Status must be 'kept' or 'removed'.")
        if status != sp.status:
            sp.status = status
            sp.status_by_user_id = user_id
            sp.status_at = datetime.now(timezone.utc)
        if status == "kept":
            sp.removed_reason = None
        else:
            sp.is_key = False  # a removed paper can't be a key paper
    if removed_reason is not None:
        if removed_reason and removed_reason not in REASONS:
            raise TriageError("Unknown reason.")
        if sp.status == "removed":
            sp.removed_reason = removed_reason or None
    if is_key is not None:
        if is_key and sp.status == "removed":
            raise TriageError("Restore the paper before marking it as a key paper.")
        sp.is_key = bool(is_key)
    if notes is not None:
        sp.notes = notes.strip()[:4000] or None
    db.commit()
    return sp


def screening_summary(db: DBSession, session_id: int, candidates: Optional[int]) -> Dict:
    rows = (db.query(SessionPaper.status, SessionPaper.removed_reason, func.count())
            .filter(SessionPaper.session_id == session_id)
            .group_by(SessionPaper.status, SessionPaper.removed_reason).all())
    kept = sum(c for st, _, c in rows if st == "kept")
    removed = sum(c for st, _, c in rows if st == "removed")
    reasons: Dict[str, int] = {}
    for st, r, c in rows:
        if st == "removed":
            reasons[r or "unspecified"] = reasons.get(r or "unspecified", 0) + c
    key = (db.query(func.count()).select_from(SessionPaper)
           .filter(SessionPaper.session_id == session_id, SessionPaper.is_key.is_(True)).scalar())
    found = kept + removed
    # Papers added by hand (upload, DOI) were "screened" by the researcher, so the funnel never narrows the wrong way.
    screened = max(candidates, found) if candidates is not None else None
    return {"screened": screened, "found": found, "kept": kept, "removed": removed,
            "key": key or 0, "removed_reasons": reasons}
