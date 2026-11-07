"""
Working together on a session: an append-only activity log, comments, proposals
for big changes, suggested edits to someone else's writing, and last visits.
"""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


class Activity(Base):
    """One thing that happened in a session. Rows are only ever added, never edited
    (except that consecutive writing in one section by one person is merged)."""
    __tablename__ = "activity"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    kind = Column(String(40), nullable=False)          # e.g. paper_removed, gap_tracked, section_written
    target_type = Column(String(20), nullable=True)    # paper | gap | section | proposal | suggestion | session
    target_id = Column(Integer, nullable=True)
    summary = Column(Text, nullable=False)             # "removed paper 12 (off-topic)"
    data = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Comment(Base):
    """A comment thread on a paper, gap, theme or writing section (replies point at the root)."""
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    target_type = Column(String(20), nullable=False)   # paper | gap | theme | section
    target_id = Column(Integer, nullable=False)        # paper id, gap id, theme index, section id
    parent_id = Column(Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=True)
    quote = Column(Text, nullable=True)                # the sentence it's about, for writing
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    body = Column(Text, nullable=False)
    mentions = Column(JSON, nullable=True)             # user ids
    resolved = Column(Boolean, nullable=False, default=False)
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Proposal(Base):
    """A big change one editor proposes and another approves: nothing changes until then."""
    __tablename__ = "proposals"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(30), nullable=False)          # remove_paper | restore_paper | untrack_gap | delete_gap | delete_section
    target_id = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=True)              # e.g. {"reason": "off_topic"}
    reason_text = Column(Text, nullable=True)          # the proposer's own words
    proposed_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(12), nullable=False, default="pending")  # pending | approved | rejected | withdrawn
    decided_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Suggestion(Base):
    """A suggested edit to a writing section that belongs to someone else."""
    __tablename__ = "suggestions"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    section_id = Column(Integer, ForeignKey("writing_sections.id", ondelete="CASCADE"), nullable=False, index=True)
    base_text = Column(Text, nullable=True)            # the section's text when the edit was suggested
    new_text = Column(Text, nullable=False)
    note = Column(Text, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(12), nullable=False, default="pending")  # pending | accepted | rejected | withdrawn
    decided_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SessionVisit(Base):
    """When each person last looked at "What's new" in a session."""
    __tablename__ = "session_visits"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
