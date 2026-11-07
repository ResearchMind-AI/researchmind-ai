"""
How the parts of a session feed each other.

Themes and the writing guide are generated from a snapshot of the session (the kept
papers, the key papers and the gaps being tracked). `basis` records that snapshot and
`changes_since` says what moved since, so the app can refresh them quietly instead of
asking the user to press "Regenerate".
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from app.models.paper import SessionPaper
from app.models.research import Gap

THEMES_REFRESH_AFTER = 3  # kept papers added or removed before themes refresh by themselves


def tracked_gaps(db: DBSession, session_id: int) -> List[Gap]:
    return (db.query(Gap).filter(Gap.session_id == session_id,
                                 (Gap.pinned.is_(True)) | (Gap.source == "user"),
                                 Gap.status != "dropped")
            .order_by(Gap.id).all())


def basis(db: DBSession, session_id: int) -> Dict:
    rows = db.query(SessionPaper.paper_id, SessionPaper.status, SessionPaper.is_key).filter(
        SessionPaper.session_id == session_id).all()
    return {"kept": sorted(pid for pid, st, _ in rows if st == "kept"),
            "key": sorted(pid for pid, st, k in rows if st == "kept" and k),
            "gaps": sorted(g.id for g in tracked_gaps(db, session_id))}


def changes_since(old: Optional[Dict], new: Dict) -> Optional[Dict]:
    """Counts of what changed, or None if nothing did (or there is no snapshot to compare)."""
    if not old:
        return None
    def diff(k):
        a, b = set(old.get(k) or []), set(new.get(k) or [])
        return len(b - a), len(a - b)
    added, removed = diff("kept")
    key_added, key_removed = diff("key")
    gaps_added, gaps_removed = diff("gaps")
    out = {"papers_added": added, "papers_removed": removed, "key_changed": key_added + key_removed,
           "gaps_tracked": gaps_added, "gaps_untracked": gaps_removed}
    return out if any(out.values()) else None


def describe(ch: Dict) -> str:
    """'you removed 2 papers and tracked a gap' style summary for the UI."""
    def n(k, one, many):
        v = ch.get(k) or 0
        return "" if not v else (one if v == 1 else many.format(v))
    parts = [n("papers_removed", "a paper was removed", "{} papers were removed"),
             n("papers_added", "a paper was added", "{} papers were added"),
             n("key_changed", "key papers changed", "key papers changed"),
             n("gaps_tracked", "a gap was tracked", "{} gaps were tracked"),
             n("gaps_untracked", "a gap was untracked", "{} gaps were untracked")]
    parts = [p for p in parts if p]
    return (", ".join(parts[:-1]) + " and " + parts[-1]) if len(parts) > 1 else (parts[0] if parts else "")


def gap_brief(g: Gap, refs: Optional[Dict[int, int]] = None) -> str:
    """One gap, with its novelty check and the researcher's notes, for prompts."""
    line = f"- {g.title}: {g.description or ''}".rstrip()
    a = g.assessment or {}
    nov = a.get("novelty") or {}
    if nov.get("verdict"):
        verdict = {"open": "looks open", "partially_addressed": "partly addressed by recent work",
                   "addressed": "already addressed by recent work", "unknown": "novelty unclear"}.get(nov["verdict"], nov["verdict"])
        line += f"\n  Novelty check: {verdict}. {nov.get('explanation') or ''}".rstrip()
        closest = [c.get("title") for c in nov.get("closest") or [] if c.get("title")][:2]
        if closest:
            line += "\n  Closest existing work: " + "; ".join(closest)
    if g.research_question:
        line += f"\n  Research question: {g.research_question}"
    if g.notes:
        line += f"\n  Researcher's notes: {g.notes[:400]}"
    return line
