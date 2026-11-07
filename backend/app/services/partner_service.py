"""
"I noticed…" notes from the research partner.

Cheap, rule-based checks over the session (no LLM call), so they can be shown
every time the panel opens. Each has a stable id so the user can dismiss it.
"""
from typing import Dict, List

from sqlalchemy.orm import Session as DBSession

from app.models.research import WritingSection
from app.services.analysis_service import list_session_papers
from app.services.chat_service import CITE_RE
from app.services.discovery_service import get_artifact
from app.services.links_service import tracked_gaps


def _cited(text: str) -> List[int]:
    out: List[int] = []
    for m in CITE_RE.finditer(text or ""):
        for x in m.group(1).replace(";", ",").split(","):
            if x.strip().isdigit() and int(x) not in out:
                out.append(int(x))
    return out


def notices(db: DBSession, session_id: int) -> List[Dict]:
    out: List[Dict] = []
    every = list_session_papers(db, session_id, include_removed=True)
    kept = [p for p in every if p.session_link.status == "kept"]
    removed = {p.session_ref: p for p in every if p.session_link.status == "removed"}

    # 1. Writing that cites a paper the researcher removed
    for sec in db.query(WritingSection).filter(WritingSection.session_id == session_id).order_by(WritingSection.position):
        bad = [n for n in _cited(sec.user_text or "") if n in removed]
        if bad:
            refs = "".join(f"[{n}]" for n in bad)
            out.append({"id": f"removed-cite-{sec.id}-{'-'.join(map(str, bad))}",
                        "text": f"Your section \"{sec.heading}\" cites {refs}, which you removed. Restore it or cite another paper.",
                        "actions": [{"label": "Open the section", "to": f"write?section={sec.id}"},
                                    {"label": "See removed papers", "to": "papers?view=removed"}]})

    # 2. A tracked gap that recent work may already cover
    for g in tracked_gaps(db, session_id):
        nov = (g.assessment or {}).get("novelty") or {}
        if nov.get("verdict") in ("partially_addressed", "addressed"):
            closest = next((c.get("title") for c in nov.get("closest") or [] if c.get("title")), None)
            what = "partly covers" if nov["verdict"] == "partially_addressed" else "may already cover"
            out.append({"id": f"gap-covered-{g.id}-{nov['verdict']}",
                        "text": f"Recent work {what} your gap \"{g.title}\""
                                + (f", e.g. \"{closest}\"." if closest else ".")
                                + " Worth narrowing the angle before you build on it.",
                        "actions": [{"label": "Open the gap", "to": f"explore/gaps/{g.id}"},
                                    {"label": "Discuss it", "ask": "How could I narrow this gap so it's clearly different from the closest existing work?", "gap_id": g.id}]})

    # 3. Key papers that are abstract only
    weak = [p for p in kept if p.session_link.is_key and not p.full_text]
    if weak:
        refs = "".join(f"[{p.session_ref}]" for p in weak[:4])
        out.append({"id": "key-abstract-only-" + "-".join(str(p.id) for p in weak[:4]),
                    "text": f"Key paper{'s' if len(weak) > 1 else ''} {refs} {'are' if len(weak) > 1 else 'is'} abstract only. "
                            "Upload the PDF so answers and checks can use the full text.",
                    "actions": [{"label": "Go to papers", "to": "papers?view=key"}]})

    # 4. No key papers yet in a sizeable session
    if len(kept) >= 10 and not any(p.session_link.is_key for p in kept):
        out.append({"id": "no-key-papers",
                    "text": "Star a few key papers. Answers and the writing guide will lead with them.",
                    "actions": [{"label": "Review papers", "to": "papers"}]})

    # 5. Themes made before papers changed a lot (they refresh when Explore opens)
    a = get_artifact(db, session_id, "analysis") or {}
    if a.get("themes") and a.get("basis"):
        from app.services.links_service import THEMES_REFRESH_AFTER, basis, changes_since
        ch = changes_since(a["basis"], basis(db, session_id)) or {}
        if ch.get("papers_added", 0) + ch.get("papers_removed", 0) >= THEMES_REFRESH_AFTER:
            out.append({"id": "themes-stale", "text": "Your papers changed since the themes were made. Open Explore to update them.",
                        "actions": [{"label": "Open Explore", "to": "explore/themes"}]})
    return out
