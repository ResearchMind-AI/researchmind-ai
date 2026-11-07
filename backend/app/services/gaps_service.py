"""
Gaps workspace: AI-suggested and user-added research gaps.

- AI gaps are regenerated on demand; pinned gaps and user gaps are never touched.
- Users pin gaps, set a status, keep notes and discuss each gap in its own chat.
- Any gap can be assessed: which session papers support or contradict it, and a
  fresh literature search ("novelty check") to see whether someone has already
  addressed it.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from app.models.research import Gap, SessionMessage
from app.services.analysis_service import list_session_papers, reference_numbers
from app.services.discovery_service import all_sources, get_artifact
from app.services.embedding_service import EmbeddingService
from app.services.llm import LLMClient
from app.services.vector_store import VectorStoreService

logger = logging.getLogger(__name__)

STATUSES = ["open", "exploring", "promising", "dropped"]


class GapError(Exception):
    pass


def list_gaps(db: DBSession, session_id: int) -> List[Gap]:
    """All gaps for a session. Imports gaps saved by older versions (stored as JSON)."""
    gaps = db.query(Gap).filter(Gap.session_id == session_id).order_by(Gap.id).all()
    if not gaps:
        legacy = (get_artifact(db, session_id, "analysis") or {}).get("gaps") or []
        if legacy:
            save_ai_gaps(db, session_id, legacy)
            gaps = db.query(Gap).filter(Gap.session_id == session_id).order_by(Gap.id).all()
    return gaps


def save_ai_gaps(db: DBSession, session_id: int, gaps: List[Dict]) -> List[Gap]:
    """Replace unpinned AI gaps (and their chat threads) with a new set."""
    old = db.query(Gap).filter(Gap.session_id == session_id, Gap.source == "ai", Gap.pinned.is_(False)).all()
    old_ids = [g.id for g in old]
    if old_ids:
        db.query(SessionMessage).filter(SessionMessage.gap_id.in_(old_ids)).delete(synchronize_session=False)
        for g in old:
            db.delete(g)
    rows = []
    for g in gaps:
        row = Gap(session_id=session_id, title=str(g.get("title", ""))[:300] or "Untitled gap",
                  description=g.get("description"), gap_type=g.get("gap_type"),
                  research_question=g.get("research_question"), confidence=g.get("confidence"),
                  evidence_paper_ids=g.get("evidence_paper_ids") or [], source="ai")
        db.add(row)
        rows.append(row)
    db.commit()
    return rows


def get_gap(db: DBSession, gap_id: int) -> Optional[Gap]:
    return db.get(Gap, gap_id)


def update_gap(db: DBSession, gap: Gap, *, pinned: Optional[bool] = None, status: Optional[str] = None,
               notes: Optional[str] = None, research_question: Optional[str] = None) -> Gap:
    if pinned is not None:
        gap.pinned = pinned
    if status is not None:
        if status not in STATUSES:
            raise GapError(f"Status must be one of {STATUSES}")
        gap.status = status
    if notes is not None:
        gap.notes = notes
    if research_question is not None:
        gap.research_question = research_question.strip() or None
    db.commit()
    return gap


def delete_gap(db: DBSession, gap: Gap) -> None:
    db.query(SessionMessage).filter(SessionMessage.gap_id == gap.id).delete(synchronize_session=False)
    db.delete(gap)
    db.commit()


def add_user_gap(db: DBSession, session_id: int, user_id: int, title: str, description: str = "") -> Gap:
    title = (title or "").strip()
    if len(title) < 5:
        raise GapError("Give the gap a short title (at least 5 characters).")
    gap = Gap(session_id=session_id, title=title[:300], description=(description or "").strip() or None,
              source="user", pinned=True, status="exploring", created_by=user_id, evidence_paper_ids=[])
    db.add(gap)
    db.commit()
    return gap


async def _session_evidence(db: DBSession, gap: Gap, llm: LLMClient) -> Dict:
    papers = list_session_papers(db, gap.session_id)
    refs = reference_numbers(papers)
    by_n = {n: p for p in papers for n in [refs[p.id]]}
    text = f"{gap.title}. {gap.description or ''}"
    vec = await EmbeddingService().generate_embedding(text)
    hits = VectorStoreService(db).search(gap.session_id, vec, n_results=30)
    chosen, seen = [], {}
    for h in hits:
        if h["paper_id"] in refs and seen.get(h["paper_id"], 0) < 2:
            seen[h["paper_id"]] = seen.get(h["paper_id"], 0) + 1
            chosen.append(h)
        if len(chosen) >= 12:
            break
    if not chosen:
        return {"supporting": [], "contradicting": [], "summary": "No papers in this session yet."}
    blocks = "\n\n".join(f"[{refs[h['paper_id']]}] {by_n[refs[h['paper_id']]].title}\n{h['text'][:700]}"
                         for h in chosen)
    prompt = f"""TASK: gap_evidence
A researcher proposes this research gap:
Title: {gap.title}
Description: {gap.description or '(none)'}

Excerpts from papers in their session:
{blocks}

Using ONLY these excerpts:
- "supporting": papers whose content suggests the gap is real (e.g. they call for this work, or
  cover only part of it). Give the bracket number and a one-sentence reason.
- "contradicting": papers that already seem to address the gap. Number + reason.
- "summary": 2-3 sentences on how well the session's evidence supports this gap.
- "research_question": one concrete, answerable research question for the gap.

Return JSON: {{"supporting": [{{"n": 3, "why": "..."}}], "contradicting": [{{"n": 5, "why": "..."}}],
"summary": "...", "research_question": "..."}}"""
    data = await llm.complete_json(prompt, max_tokens=1200)
    allowed = set(by_n)

    def clean(items):
        out = []
        for it in items or []:
            if isinstance(it, dict) and isinstance(it.get("n"), int) and it["n"] in allowed:
                p = by_n[it["n"]]
                out.append({"paper_id": p.id, "n": it["n"], "title": p.title, "why": str(it.get("why", ""))})
        return out
    return {"supporting": clean(data.get("supporting")), "contradicting": clean(data.get("contradicting")),
            "summary": str(data.get("summary", "")), "research_question": str(data.get("research_question", ""))}


async def _novelty_check(db: DBSession, gap: Gap, llm: LLMClient) -> Dict:
    """Search the wider literature for papers that may already address the gap."""
    query = gap.title if len(gap.title) > 15 else f"{gap.title} {gap.description or ''}"
    sources = all_sources()
    results = []
    outs = await asyncio.gather(sources["openalex"].search(query[:200], 12),
                                sources["semantic_scholar"].search(query[:200], 8),
                                return_exceptions=True)
    for out in outs:
        if not isinstance(out, Exception):
            results.extend(out)
    seen, candidates = set(), []
    for r in results:
        key = (r.doi or r.title).lower()
        if key not in seen and r.abstract:
            seen.add(key)
            candidates.append(r)
    candidates = candidates[:15]
    if not candidates:
        return {"verdict": "unknown", "explanation": "The search returned no papers to compare against "
                "(the paper sources may be busy). Try again later.", "closest": []}
    listing = "\n\n".join(f"({i}) {c.title} ({(c.publication_date or 'n.d.')[:4]})\n{c.abstract[:400]}"
                          for i, c in enumerate(candidates))
    prompt = f"""TASK: novelty_check
Research gap:
Title: {gap.title}
Description: {gap.description or '(none)'}

Recent papers found by a fresh literature search:
{listing}

Has this gap already been addressed? Judge strictly from the abstracts:
- "verdict": "open" (no paper addresses it), "partially_addressed" (some papers cover part of it),
  or "addressed" (at least one paper directly addresses it)
- "explanation": 2-3 sentences
- "closest": up to 3 of the most relevant papers, by their (number), each with a one-sentence reason

Return JSON: {{"verdict": "...", "explanation": "...", "closest": [{{"index": 0, "why": "..."}}]}}"""
    data = await llm.complete_json(prompt, max_tokens=900)
    closest = []
    for c in data.get("closest") or []:
        i = c.get("index") if isinstance(c, dict) else None
        if isinstance(i, int) and 0 <= i < len(candidates):
            p = candidates[i]
            closest.append({"title": p.title, "year": (p.publication_date or "")[:4] or None,
                            "url": p.url or (f"https://doi.org/{p.doi}" if p.doi else None),
                            "why": str(c.get("why", ""))})
    verdict = data.get("verdict") if data.get("verdict") in ("open", "partially_addressed", "addressed") else "unknown"
    return {"verdict": verdict, "explanation": str(data.get("explanation", "")), "closest": closest,
            "searched": len(candidates)}


async def assess_gap(db: DBSession, gap: Gap, llm: Optional[LLMClient] = None) -> Gap:
    """Evidence from the session + a novelty check. Stores the result on the gap."""
    llm = llm or LLMClient()
    evidence, novelty = await asyncio.gather(_session_evidence(db, gap, llm), _novelty_check(db, gap, llm))
    gap.assessment = {"evidence": evidence, "novelty": novelty,
                      "checked_at": datetime.now(timezone.utc).isoformat()}
    if gap.source == "user" and not gap.evidence_paper_ids:
        gap.evidence_paper_ids = [e["paper_id"] for e in evidence["supporting"]][:4]
    if not gap.research_question and evidence.get("research_question"):
        gap.research_question = evidence["research_question"]
    db.commit()
    return gap


def gap_messages(db: DBSession, gap_id: int) -> List[SessionMessage]:
    return (db.query(SessionMessage).filter(SessionMessage.gap_id == gap_id)
            .order_by(SessionMessage.id).all())
