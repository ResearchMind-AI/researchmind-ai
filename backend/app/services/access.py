"""
Session access rules, used by the API.

- Owner (creator), lead, contributor: can edit (run discovery, upload, analyse,
  chat, export).
- Reviewer, viewer: read-only. They can read results and download exports but
  cannot change the session (chat writes history, so it is edit-only too).
- Owner and lead can share the session with other registered users.
"""
from typing import List, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session as DBSession

from app.models.session import Session, SessionMember, SessionMemberRole
from app.models.user import User

EDIT_ROLES = {SessionMemberRole.LEAD, SessionMemberRole.CONTRIBUTOR}
MANAGE_ROLES = {SessionMemberRole.LEAD}
SHAREABLE_ROLES = {"viewer": SessionMemberRole.VIEWER, "contributor": SessionMemberRole.CONTRIBUTOR}


class AccessError(Exception):
    pass


def role_of(db: DBSession, session: Session, user: User) -> Optional[str]:
    if session.creator_id == user.id:
        return "owner"
    m = db.query(SessionMember).filter(SessionMember.session_id == session.id,
                                       SessionMember.user_id == user.id).first()
    return m.role.value if m else None


def can_view(db: DBSession, session: Session, user: User) -> bool:
    return role_of(db, session, user) is not None


def can_edit(db: DBSession, session: Session, user: User) -> bool:
    role = role_of(db, session, user)
    return role == "owner" or role in {r.value for r in EDIT_ROLES}


def can_manage(db: DBSession, session: Session, user: User) -> bool:
    role = role_of(db, session, user)
    return role == "owner" or role in {r.value for r in MANAGE_ROLES}


def list_user_sessions(db: DBSession, user: User) -> List[Session]:
    member_ids = db.query(SessionMember.session_id).filter(SessionMember.user_id == user.id)
    return (db.query(Session)
            .filter(or_(Session.creator_id == user.id, Session.id.in_(member_ids)))
            .order_by(Session.updated_at.desc().nullslast(), Session.created_at.desc())
            .all())


def share_session(db: DBSession, session: Session, by_user: User, email: str, role: str) -> SessionMember:
    if not can_manage(db, session, by_user):
        raise AccessError("Only the session owner can share it.")
    if role not in SHAREABLE_ROLES:
        raise AccessError("Role must be 'viewer' or 'contributor'.")
    target = db.query(User).filter(func.lower(User.email) == email.strip().lower()).first()
    if not target:
        raise AccessError("No account with that email. Ask them to sign up first, then share again.")
    if target.id == session.creator_id:
        raise AccessError("That person already owns this session.")
    m = db.query(SessionMember).filter(SessionMember.session_id == session.id,
                                       SessionMember.user_id == target.id).first()
    if m:
        m.role = SHAREABLE_ROLES[role]
    else:
        m = SessionMember(session_id=session.id, user_id=target.id, role=SHAREABLE_ROLES[role])
        db.add(m)
    db.commit()
    return m


def unshare_session(db: DBSession, session: Session, by_user: User, user_id: int) -> None:
    if not can_manage(db, session, by_user):
        raise AccessError("Only the session owner can change sharing.")
    db.query(SessionMember).filter(SessionMember.session_id == session.id,
                                   SessionMember.user_id == user_id).delete()
    db.commit()
