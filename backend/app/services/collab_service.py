"""
Working together on a session.

- Every change is recorded in an append-only activity log (who, what, when).
- With more than one editor, big changes become proposals that someone else
  approves: removing or restoring a paper, untracking or deleting a gap, deleting a
  section. Nothing changes until then. With one editor, they happen straight away.
- Each writing section belongs to whoever started it. Others suggest edits, which
  the owner accepts or rejects. Saves carry a version so nobody overwrites anyone.
- Comments (with @mentions) on papers, gaps, themes and sections; viewers can comment.
- "What's new" lists what others did since your last visit, and what needs you.
"""
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from app.models.collab import Activity, Comment, Proposal, SessionVisit, Suggestion
from app.models.paper import SessionPaper
from app.models.research import Gap, WritingSection
from app.models.session import Session, SessionMember
from app.models.user import User
from app.services import access

PROPOSAL_KINDS = ("remove_paper", "restore_paper", "untrack_gap", "delete_gap", "delete_section")
COMMENT_TARGETS = ("paper", "gap", "theme", "section")
WRITE_MERGE_SECONDS = 30 * 60


class CollabError(Exception):
    def __init__(self, message: str, status: int = 400, data: Optional[dict] = None):
        super().__init__(message)
        self.status, self.data = status, data


def now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


# ── People ───────────────────────────────────────────────────────────────────

def members(db: DBSession, session: Session) -> List[Dict]:
    """Everyone with access, owner first: id, name, email, role, can_edit."""
    owner = db.get(User, session.creator_id)
    out = [{"id": owner.id, "name": owner.full_name or owner.email.split("@")[0], "email": owner.email,
            "role": "owner", "can_edit": True}]
    for m in db.query(SessionMember).filter(SessionMember.session_id == session.id).order_by(SessionMember.id):
        u = db.get(User, m.user_id)
        out.append({"id": u.id, "name": u.full_name or u.email.split("@")[0], "email": u.email,
                    "role": m.role.value, "can_edit": m.role in access.EDIT_ROLES})
    return out


def editor_ids(db: DBSession, session: Session) -> List[int]:
    return [m["id"] for m in members(db, session) if m["can_edit"]]


def is_collaborative(db: DBSession, session: Session) -> bool:
    """Proposals and suggested edits apply only when more than one person can edit."""
    return len(editor_ids(db, session)) > 1


def name_of(db: DBSession, user_id: Optional[int]) -> Optional[str]:
    if not user_id:
        return None
    u = db.get(User, user_id)
    return (u.full_name or u.email.split("@")[0]) if u else None


# ── Activity ─────────────────────────────────────────────────────────────────

def log(db: DBSession, session_id: int, user_id: Optional[int], kind: str, summary: str,
        target_type: Optional[str] = None, target_id: Optional[int] = None,
        data: Optional[dict] = None, commit: bool = True) -> Activity:
    if kind == "section_written" and target_id is not None:
        # Consecutive writing in one section by one person is one entry, not one per autosave.
        last = (db.query(Activity).filter(Activity.session_id == session_id).order_by(Activity.id.desc()).first())
        if (last and last.kind == kind and last.user_id == user_id and last.target_id == target_id
                and (now() - _aware(last.updated_at or last.created_at)).total_seconds() < WRITE_MERGE_SECONDS):
            words = (last.data or {}).get("words_added", 0) + (data or {}).get("words_added", 0)
            last.data = {**(data or {}), "words_added": max(0, words)}
            last.summary = summary if words <= 0 else re.sub(r"wrote [\-\d]+ words", f"wrote {words} words", summary)
            last.updated_at = now()
            if commit:
                db.commit()
            return last
    t = now()  # set here (not by the database) so ordering against "last seen" is exact
    row = Activity(session_id=session_id, user_id=user_id, kind=kind, summary=summary,
                   target_type=target_type, target_id=target_id, data=data, created_at=t, updated_at=t)
    db.add(row)
    if commit:
        db.commit()
    return row


def activity_out(db: DBSession, a: Activity) -> Dict:
    return {"id": a.id, "kind": a.kind, "summary": a.summary, "user_id": a.user_id,
            "user_name": name_of(db, a.user_id), "target_type": a.target_type, "target_id": a.target_id,
            "data": a.data, "at": _aware(a.updated_at or a.created_at)}


def history(db: DBSession, session_id: int, target_type: str, target_id: int) -> List[Dict]:
    rows = (db.query(Activity).filter(Activity.session_id == session_id, Activity.target_type == target_type,
                                      Activity.target_id == target_id).order_by(Activity.id.desc()).limit(100).all())
    return [activity_out(db, a) for a in rows]


# ── Proposals ────────────────────────────────────────────────────────────────

def _paper_ref(db: DBSession, session_id: int, paper_id: int) -> SessionPaper:
    sp = db.query(SessionPaper).filter(SessionPaper.session_id == session_id, SessionPaper.paper_id == paper_id).first()
    if not sp:
        raise CollabError("That paper is not in this session.", 404)
    return sp


def describe_target(db: DBSession, session_id: int, kind: str, target_id: int) -> str:
    if kind in ("remove_paper", "restore_paper"):
        return f"paper {_paper_ref(db, session_id, target_id).ref_no}"
    if kind in ("untrack_gap", "delete_gap"):
        g = db.get(Gap, target_id)
        return f"gap \"{g.title}\"" if g else "a gap"
    s = db.get(WritingSection, target_id)
    return f"section \"{s.heading}\"" if s else "a section"


def _check_target(db: DBSession, session: Session, kind: str, target_id: int) -> None:
    if kind in ("remove_paper", "restore_paper"):
        sp = _paper_ref(db, session.id, target_id)
        if kind == "remove_paper" and sp.status == "removed":
            raise CollabError("That paper is already removed.")
        if kind == "restore_paper" and sp.status == "kept":
            raise CollabError("That paper is already kept.")
    elif kind in ("untrack_gap", "delete_gap"):
        g = db.get(Gap, target_id)
        if not g or g.session_id != session.id:
            raise CollabError("Gap not found.", 404)
    elif kind == "delete_section":
        s = db.get(WritingSection, target_id)
        if not s or s.session_id != session.id:
            raise CollabError("Section not found.", 404)
    else:
        raise CollabError("Unknown kind of change.")


def propose(db: DBSession, session: Session, user: User, kind: str, target_id: int,
            payload: Optional[dict] = None, reason_text: Optional[str] = None) -> Proposal:
    if kind not in PROPOSAL_KINDS:
        raise CollabError("Unknown kind of change.")
    _check_target(db, session, kind, target_id)
    dup = db.query(Proposal).filter(Proposal.session_id == session.id, Proposal.kind == kind,
                                    Proposal.target_id == target_id, Proposal.status == "pending").first()
    if dup:
        raise CollabError(f"{name_of(db, dup.proposed_by)} has already proposed this. Approve or reject it instead.", 409)
    p = Proposal(created_at=now(), session_id=session.id, kind=kind, target_id=target_id, payload=payload or {},
                 reason_text=(reason_text or "").strip()[:1000] or None, proposed_by=user.id)
    db.add(p)
    db.flush()
    what = {"remove_paper": "removing", "restore_paper": "restoring", "untrack_gap": "untracking",
            "delete_gap": "deleting", "delete_section": "deleting"}[kind]
    log(db, session.id, user.id, "proposal_created", f"proposed {what} {describe_target(db, session.id, kind, target_id)}",
        "proposal", p.id, {"kind": kind, "target_id": target_id, "reason": (payload or {}).get("reason")}, commit=False)
    db.commit()
    return p


def apply_change(db: DBSession, session: Session, user: User, kind: str, target_id: int,
                 payload: Optional[dict] = None, via: Optional[Proposal] = None) -> None:
    """Make the change (directly, or because a proposal was approved) and log it."""
    from app.services import gaps_service as gs
    from app.services import triage_service as ts
    payload = payload or {}
    actor = via.proposed_by if via else user.id
    suffix = f" (approved by {name_of(db, user.id)})" if via else ""
    if kind == "remove_paper":
        sp = ts.update_paper(db, session.id, target_id, actor, status="removed",
                             removed_reason=payload.get("reason") or None)
        why = f" ({sp.removed_reason.replace('_', '-')})" if sp.removed_reason else ""
        log(db, session.id, actor, "paper_removed", f"removed paper {sp.ref_no}{why}{suffix}", "paper", target_id)
    elif kind == "restore_paper":
        sp = ts.update_paper(db, session.id, target_id, actor, status="kept")
        log(db, session.id, actor, "paper_restored", f"restored paper {sp.ref_no}{suffix}", "paper", target_id)
    elif kind == "untrack_gap":
        g = db.get(Gap, target_id)
        gs.update_gap(db, g, pinned=False)
        log(db, session.id, actor, "gap_untracked", f"stopped tracking gap \"{g.title}\"{suffix}", "gap", target_id)
    elif kind == "delete_gap":
        g = db.get(Gap, target_id)
        title = g.title
        db.query(Comment).filter(Comment.session_id == session.id, Comment.target_type == "gap",
                                 Comment.target_id == target_id).delete(synchronize_session=False)
        gs.delete_gap(db, g)
        log(db, session.id, actor, "gap_deleted", f"deleted gap \"{title}\"{suffix}", "gap", target_id)
    elif kind == "delete_section":
        from app.services import writing_service as ws
        s = db.get(WritingSection, target_id)
        heading = s.heading
        ws.delete_section(db, s)
        log(db, session.id, actor, "section_deleted", f"deleted section \"{heading}\"{suffix}", "section", target_id)


def change_or_propose(db: DBSession, session: Session, user: User, kind: str, target_id: int,
                      payload: Optional[dict] = None, reason_text: Optional[str] = None) -> Optional[Proposal]:
    """Apply straight away when working alone; otherwise create a proposal."""
    if is_collaborative(db, session):
        return propose(db, session, user, kind, target_id, payload, reason_text)
    _check_target(db, session, kind, target_id)
    apply_change(db, session, user, kind, target_id, payload)
    return None


def decide(db: DBSession, session: Session, user: User, proposal_id: int, decision: str) -> Proposal:
    p = db.get(Proposal, proposal_id)
    if not p or p.session_id != session.id:
        raise CollabError("Proposal not found.", 404)
    if p.status != "pending":
        raise CollabError(f"This proposal was already {p.status}.", 409)
    if decision == "withdraw":
        if p.proposed_by != user.id:
            raise CollabError("Only the person who proposed it can withdraw it.", 403)
    elif decision in ("approve", "reject"):
        if p.proposed_by == user.id and is_collaborative(db, session):
            raise CollabError("Someone else needs to approve or reject your proposal.", 403)
    else:
        raise CollabError("Decision must be approve, reject or withdraw.")
    target = describe_target(db, session.id, p.kind, p.target_id)
    if decision == "approve":
        _check_target(db, session, p.kind, p.target_id)
        p.status = "approved"
        apply_change(db, session, user, p.kind, p.target_id, p.payload, via=p)
    else:
        p.status = "rejected" if decision == "reject" else "withdrawn"
    p.decided_by, p.decided_at = user.id, now()
    verb = {"approve": "approved", "reject": "kept things as they were for", "withdraw": "withdrew the proposal for"}[decision]
    log(db, session.id, user.id, f"proposal_{p.status}", f"{verb} {target}"
        + (f" (proposed by {name_of(db, p.proposed_by)})" if decision != "withdraw" else ""), "proposal", p.id,
        {"kind": p.kind, "target_id": p.target_id})
    return p


def proposal_out(db: DBSession, p: Proposal) -> Dict:
    return {"id": p.id, "kind": p.kind, "target_id": p.target_id, "payload": p.payload or {},
            "reason_text": p.reason_text, "status": p.status, "proposed_by": p.proposed_by,
            "proposed_by_name": name_of(db, p.proposed_by), "decided_by": p.decided_by,
            "decided_by_name": name_of(db, p.decided_by), "created_at": _aware(p.created_at)}


def pending_proposals(db: DBSession, session_id: int) -> List[Proposal]:
    return (db.query(Proposal).filter(Proposal.session_id == session_id, Proposal.status == "pending")
            .order_by(Proposal.id).all())


# ── Writing: ownership, versions, suggested edits ─────────────────────────────

def save_section_text(db: DBSession, session: Session, user: User, section: WritingSection, text: str,
                      heading: Optional[str], base_version: Optional[int]) -> WritingSection:
    from app.services import writing_service as ws
    if is_collaborative(db, session) and section.owner_id not in (None, user.id):
        raise CollabError(f"This section is {name_of(db, section.owner_id)}'s. Suggest an edit instead.", 403)
    if base_version is not None and base_version != (section.version or 0):
        raise CollabError(f"{name_of(db, section.updated_by) or 'Someone'} changed this section while you were editing.",
                          409, {"current_text": section.user_text or "", "version": section.version or 0,
                                "updated_by_name": name_of(db, section.updated_by)})
    before = ws.word_count(section.user_text)
    ws.save_text(db, section, text, user.id, heading)
    if section.owner_id is None and text.strip():
        section.owner_id = user.id
    section.version = (section.version or 0) + 1
    db.commit()
    added = ws.word_count(text) - before
    if added or heading:
        log(db, session.id, user.id, "section_written", f"wrote {added} words in \"{section.heading}\"", "section",
            section.id, {"words_added": added})
    return section


def suggest_edit(db: DBSession, session: Session, user: User, section: WritingSection, new_text: str,
                 note: Optional[str] = None) -> Suggestion:
    if section.owner_id in (None, user.id):
        raise CollabError("This is your section (or nobody's yet): just edit it.")
    if (new_text or "").strip() == (section.user_text or "").strip():
        raise CollabError("The suggestion is the same as the current text.")
    s = Suggestion(created_at=now(), session_id=session.id, section_id=section.id, base_text=section.user_text or "",
                   new_text=new_text, note=(note or "").strip() or None, user_id=user.id)
    db.add(s)
    db.flush()
    log(db, session.id, user.id, "suggestion_created", f"suggested an edit in \"{section.heading}\"", "section",
        section.id, {"suggestion_id": s.id}, commit=False)
    db.commit()
    return s


def decide_suggestion(db: DBSession, session: Session, user: User, suggestion_id: int, decision: str) -> Suggestion:
    s = db.get(Suggestion, suggestion_id)
    if not s or s.session_id != session.id:
        raise CollabError("Suggestion not found.", 404)
    if s.status != "pending":
        raise CollabError(f"This suggestion was already {s.status}.", 409)
    section = db.get(WritingSection, s.section_id)
    if decision == "withdraw":
        if s.user_id != user.id:
            raise CollabError("Only the person who suggested it can withdraw it.", 403)
        s.status = "withdrawn"
    elif decision in ("accept", "reject"):
        if section.owner_id not in (user.id, None):
            raise CollabError(f"Only {name_of(db, section.owner_id)} can accept or reject edits to this section.", 403)
        if decision == "accept":
            if (section.user_text or "") != (s.base_text or ""):
                raise CollabError("The section has changed since this edit was suggested. Ask for it to be suggested again.",
                                  409, {"current_text": section.user_text or ""})
            from app.services import writing_service as ws
            ws.save_text(db, section, s.new_text, user.id)
            section.version = (section.version or 0) + 1
        s.status = "accepted" if decision == "accept" else "rejected"
    else:
        raise CollabError("Decision must be accept, reject or withdraw.")
    s.decided_by, s.decided_at = user.id, now()
    verb = {"accepted": "accepted", "rejected": "rejected", "withdrawn": "withdrew"}[s.status]
    who = f"{name_of(db, s.user_id)}'s" if s.status != "withdrawn" else "their"
    log(db, session.id, user.id, f"suggestion_{s.status}", f"{verb} {who} edit in \"{section.heading}\"", "section",
        section.id, {"suggestion_id": s.id})
    return s


def suggestion_out(db: DBSession, s: Suggestion) -> Dict:
    return {"id": s.id, "section_id": s.section_id, "base_text": s.base_text, "new_text": s.new_text,
            "note": s.note, "user_id": s.user_id, "user_name": name_of(db, s.user_id), "status": s.status,
            "created_at": _aware(s.created_at)}


def pending_suggestions(db: DBSession, session_id: int, section_id: Optional[int] = None) -> List[Suggestion]:
    q = db.query(Suggestion).filter(Suggestion.session_id == session_id, Suggestion.status == "pending")
    if section_id is not None:
        q = q.filter(Suggestion.section_id == section_id)
    return q.order_by(Suggestion.id).all()


# ── Comments ─────────────────────────────────────────────────────────────────

def _mentions(text: str, people: List[Dict], author_id: int) -> List[int]:
    found = []
    for m in re.finditer(r"@([\w.\-]+)", text or ""):
        word = m.group(1).lower()
        for p in people:
            first = p["name"].split()[0].lower() if p["name"] else ""
            if p["id"] != author_id and word in (first, p["email"].split("@")[0].lower()) and p["id"] not in found:
                found.append(p["id"])
    return found


def add_comment(db: DBSession, session: Session, user: User, target_type: str, target_id: int, body: str,
                quote: Optional[str] = None, parent_id: Optional[int] = None) -> Comment:
    body = (body or "").strip()
    if not body:
        raise CollabError("Write something first.")
    if parent_id:
        parent = db.get(Comment, parent_id)
        if not parent or parent.session_id != session.id:
            raise CollabError("Comment not found.", 404)
        if parent.parent_id:
            parent = db.get(Comment, parent.parent_id)
        target_type, target_id, parent_id = parent.target_type, parent.target_id, parent.id
        parent.resolved = False  # a reply reopens the thread
    elif target_type not in COMMENT_TARGETS:
        raise CollabError("You can comment on papers, gaps, themes and sections.")
    c = Comment(created_at=now(), session_id=session.id, target_type=target_type, target_id=target_id, parent_id=parent_id,
                quote=(quote or "").strip()[:500] or None, user_id=user.id, body=body[:4000],
                mentions=_mentions(body, members(db, session), user.id))
    db.add(c)
    db.flush()
    where = {"paper": "a paper", "gap": "a gap", "theme": "a theme", "section": "a section"}[target_type]
    log(db, session.id, user.id, "comment_added", f"{'replied to a comment' if parent_id else 'commented'} on {where}",
        target_type, target_id, {"comment_id": c.id, "mentions": c.mentions or [], "excerpt": body[:140]}, commit=False)
    db.commit()
    return c


def resolve_comment(db: DBSession, session: Session, user: User, comment_id: int, resolved: bool = True) -> Comment:
    c = db.get(Comment, comment_id)
    if not c or c.session_id != session.id:
        raise CollabError("Comment not found.", 404)
    root = db.get(Comment, c.parent_id) if c.parent_id else c
    root.resolved, root.resolved_by = resolved, (user.id if resolved else None)
    db.commit()
    return root


def threads(db: DBSession, session_id: int, target_type: Optional[str] = None,
            target_id: Optional[int] = None) -> List[Dict]:
    q = db.query(Comment).filter(Comment.session_id == session_id)
    if target_type:
        q = q.filter(Comment.target_type == target_type)
    if target_id is not None:
        q = q.filter(Comment.target_id == target_id)
    rows = q.order_by(Comment.id).all()
    out: Dict[int, Dict] = {}
    for c in rows:
        item = {"id": c.id, "user_id": c.user_id, "user_name": name_of(db, c.user_id), "body": c.body,
                "mentions": c.mentions or [], "created_at": _aware(c.created_at)}
        if c.parent_id is None:
            out[c.id] = {**item, "target_type": c.target_type, "target_id": c.target_id, "quote": c.quote,
                         "resolved": c.resolved, "replies": []}
        elif c.parent_id in out:
            out[c.parent_id]["replies"].append(item)
    return list(out.values())


# ── What's new ───────────────────────────────────────────────────────────────

def _visit(db: DBSession, session_id: int, user_id: int) -> SessionVisit:
    v = db.query(SessionVisit).filter(SessionVisit.session_id == session_id, SessionVisit.user_id == user_id).first()
    if not v:
        v = SessionVisit(session_id=session_id, user_id=user_id, last_seen_at=None)
        db.add(v)
        db.flush()
    return v


def whats_new(db: DBSession, session: Session, user: User) -> Dict:
    v = _visit(db, session.id, user.id)
    since = _aware(v.last_seen_at)
    needs: List[Dict] = []
    can_edit = access.can_edit(db, session, user)
    for p in pending_proposals(db, session.id):
        if p.proposed_by != user.id and can_edit:
            needs.append({"type": "proposal", "id": p.id, "user_name": name_of(db, p.proposed_by),
                          "text": f"proposed {'removing' if p.kind == 'remove_paper' else 'restoring' if p.kind == 'restore_paper' else 'untracking' if p.kind == 'untrack_gap' else 'deleting'} "
                                  f"{describe_target(db, session.id, p.kind, p.target_id)}",
                          "kind": p.kind, "target_id": p.target_id, "at": _aware(p.created_at)})
    mine = {s.id for s in db.query(WritingSection).filter(WritingSection.session_id == session.id,
                                                           WritingSection.owner_id == user.id)}
    for s in pending_suggestions(db, session.id):
        if s.section_id in mine:
            sec = db.get(WritingSection, s.section_id)
            needs.append({"type": "suggestion", "id": s.id, "user_name": name_of(db, s.user_id),
                          "text": f"suggested an edit in your section \"{sec.heading}\"", "section_id": s.section_id,
                          "at": _aware(s.created_at)})
    for c in db.query(Comment).filter(Comment.session_id == session.id, Comment.user_id != user.id).order_by(Comment.id):
        root = db.get(Comment, c.parent_id) if c.parent_id else c
        if user.id in (c.mentions or []) and not root.resolved:
            needs.append({"type": "mention", "id": c.id, "user_name": name_of(db, c.user_id),
                          "text": f"mentioned you: \"{c.body[:120]}\"", "target_type": c.target_type,
                          "target_id": c.target_id, "at": _aware(c.created_at)})
    q = db.query(Activity).filter(Activity.session_id == session.id, Activity.user_id != user.id)
    rows = q.order_by(Activity.id.desc()).limit(60).all()
    changes = [activity_out(db, a) for a in rows]
    unseen = [c for c in changes if since is None or (c["at"] and c["at"] > since)]
    db.commit()
    return {"last_seen_at": since, "needs_you": needs, "changes": changes[:40], "unseen": len(unseen),
            "count": len(needs) + len(unseen)}


def mark_seen(db: DBSession, session: Session, user: User) -> None:
    _visit(db, session.id, user.id).last_seen_at = now()
    db.commit()


# ── Presence (in memory: fine for a single app instance) ─────────────────────

_PRESENCE: Dict[int, Dict[int, tuple]] = {}
PRESENCE_TTL = 75


def heartbeat(session_id: int, user_id: int, where: str) -> None:
    _PRESENCE.setdefault(session_id, {})[user_id] = ((where or "")[:80], time.time())


def present(db: DBSession, session_id: int, except_user: int) -> List[Dict]:
    cutoff = time.time() - PRESENCE_TTL
    people = _PRESENCE.get(session_id, {})
    return [{"user_id": uid, "name": name_of(db, uid), "where": where}
            for uid, (where, ts) in people.items() if ts >= cutoff and uid != except_user]
