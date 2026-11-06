"""
Writing guide: the researcher writes the literature review; the AI guides.

- generate_outline: one section per theme plus introduction, gaps and conclusion.
  Each section gets points to cover (with supporting papers), where studies agree
  and disagree, guiding questions and a target length. No prose is written.
- The researcher writes each section, citing papers by their [n] numbers.
- check_section: feedback only (uncited claims, citations that don't match the
  paper, points not yet covered). The AI never writes sentences for the user.
- compile_review: the user's own text, ready for export with formatted references.
"""
import logging
import re
from typing import Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from app.models.research import Gap, WritingSection
from app.services.analysis_service import list_session_papers, reference_numbers
from app.services.chat_service import CITE_RE
from app.services.discovery_service import get_artifact, save_artifact
from app.services.embedding_service import EmbeddingService
from app.services.llm import LLMClient
from app.services.vector_store import VectorStoreService

logger = logging.getLogger(__name__)

KINDS = ("intro", "theme", "gaps", "conclusion", "custom")


class WritingError(Exception):
    pass


def list_sections(db: DBSession, session_id: int) -> List[WritingSection]:
    return (db.query(WritingSection).filter(WritingSection.session_id == session_id)
            .order_by(WritingSection.position, WritingSection.id).all())


def get_title(db: DBSession, session_id: int, default: str) -> str:
    return (get_artifact(db, session_id, "writing_meta") or {}).get("title") or default


def set_title(db: DBSession, session_id: int, title: str) -> None:
    meta = get_artifact(db, session_id, "writing_meta") or {}
    meta["title"] = title.strip()[:300]
    save_artifact(db, session_id, "writing_meta", meta)


def _clean_refs(items, allowed: set) -> List[int]:
    return [n for n in (items or []) if isinstance(n, int) and n in allowed]


async def generate_outline(db: DBSession, session_id: int, topic: str,
                           llm: Optional[LLMClient] = None) -> List[WritingSection]:
    """Create or refresh section guidance. The user's text is never deleted."""
    papers = list_session_papers(db, session_id)
    if not papers:
        raise WritingError("Add papers to the session first.")
    refs = reference_numbers(papers)
    allowed = set(refs.values())
    analysis = get_artifact(db, session_id, "analysis") or {}
    themes = analysis.get("themes") or []
    gaps = db.query(Gap).filter(Gap.session_id == session_id).order_by(Gap.pinned.desc(), Gap.id).all()
    tracked = [g for g in gaps if g.pinned or g.source == "user"] or gaps[:4]

    theme_text = "\n".join(
        f"- {t['label']}: {t['summary']} Papers: " + ", ".join(f"[{refs[i]}]" for i in t["paper_ids"][:12] if i in refs)
        for t in themes) or "(no themes yet: infer them from the papers)"
    gap_text = "\n".join(f"- {g.title}: {g.description or ''}" for g in tracked) or "(none)"
    paper_text = "\n\n".join(
        f"[{refs[p.id]}] {p.title} ({p.publication_date.year if p.publication_date else 'n.d.'})\n"
        f"{(p.abstract or (p.full_text or '')[:500] or '')[:500]}" for p in papers[:45])

    prompt = f"""TASK: writing_outline
A researcher is WRITING their own literature review on: "{topic}"
Do not write the review. Give them a writing guide.

Themes:
{theme_text}

Research gaps they are tracking:
{gap_text}

Papers (refer to them only by bracket number):
{paper_text}

Create sections in this order: one "intro", one section per theme ("theme"), one "gaps", one "conclusion".
For each section give:
- "heading": a specific heading
- "kind": intro | theme | gaps | conclusion
- "points": 3-6 points the section should cover, each a short phrase (not a finished sentence),
  with "refs": the paper numbers that support it
- "agreements": 0-3 places where studies agree (short phrases with refs in brackets)
- "disagreements": 0-3 places where studies disagree or results conflict (short phrases with refs)
- "questions": 2-3 guiding questions the writer should answer in this section
- "target_words": a sensible length (intro ~250, theme ~400-600, gaps ~300, conclusion ~200)
Also give a "title" for the review.

Return JSON: {{"title": "...", "sections": [{{"heading": "...", "kind": "theme",
"points": [{{"text": "...", "refs": [3, 7]}}], "agreements": ["... [3][7]"], "disagreements": ["..."],
"questions": ["..."], "target_words": 450}}]}}"""

    data = await (llm or LLMClient()).complete_json(prompt, max_tokens=4000)
    existing = list_sections(db, session_id)
    by_heading = {s.heading.strip().lower(): s for s in existing}
    used = set()
    result: List[WritingSection] = []
    for pos, sec in enumerate(data.get("sections") or []):
        if not isinstance(sec, dict) or not sec.get("heading"):
            continue
        guidance = {
            "points": [{"text": str(p.get("text", "")), "refs": _clean_refs(p.get("refs"), allowed)}
                       for p in sec.get("points") or [] if isinstance(p, dict) and p.get("text")][:6],
            "agreements": [str(a) for a in sec.get("agreements") or []][:3],
            "disagreements": [str(d) for d in sec.get("disagreements") or []][:3],
            "questions": [str(q) for q in sec.get("questions") or []][:3],
            "target_words": int(sec["target_words"]) if str(sec.get("target_words", "")).isdigit() else None,
        }
        kind = sec.get("kind") if sec.get("kind") in KINDS else "theme"
        row = by_heading.get(str(sec["heading"]).strip().lower())
        if row:
            used.add(row.id)
            row.guidance, row.position, row.kind = guidance, pos, kind
        else:
            row = WritingSection(session_id=session_id, position=pos, heading=str(sec["heading"])[:300],
                                 kind=kind, guidance=guidance)
            db.add(row)
        result.append(row)
    # Keep sections the user has written in (or added) even if the new outline dropped them
    for s in existing:
        if s.id not in used:
            if (s.user_text or "").strip() or s.kind == "custom":
                s.position = len(result)
                result.append(s)
            else:
                db.delete(s)
    db.commit()
    if data.get("title") and not (get_artifact(db, session_id, "writing_meta") or {}).get("title"):
        set_title(db, session_id, str(data["title"]))
    return list_sections(db, session_id)


def add_section(db: DBSession, session_id: int, heading: str) -> WritingSection:
    heading = (heading or "").strip()
    if not heading:
        raise WritingError("Give the section a heading.")
    pos = len(list_sections(db, session_id))
    row = WritingSection(session_id=session_id, position=pos, heading=heading[:300], kind="custom",
                         guidance={"points": [], "agreements": [], "disagreements": [], "questions": []})
    db.add(row)
    db.commit()
    return row


def save_text(db: DBSession, section: WritingSection, text: str, user_id: int,
              heading: Optional[str] = None) -> WritingSection:
    section.user_text = text
    if heading and heading.strip():
        section.heading = heading.strip()[:300]
    section.updated_by = user_id
    db.commit()
    return section


def move_section(db: DBSession, section: WritingSection, direction: int) -> None:
    sections = list_sections(db, section.session_id)
    i = next(k for k, s in enumerate(sections) if s.id == section.id)
    j = i + direction
    if 0 <= j < len(sections):
        sections[i], sections[j] = sections[j], sections[i]
        for pos, s in enumerate(sections):
            s.position = pos
        db.commit()


def delete_section(db: DBSession, section: WritingSection) -> None:
    db.delete(section)
    db.commit()


def word_count(text: Optional[str]) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def cited_numbers(text: str) -> List[int]:
    out: List[int] = []
    for m in CITE_RE.finditer(text or ""):
        for x in re.split(r"\s*[,;]\s*", m.group(1)):
            if int(x) not in out:
                out.append(int(x))
    return out


async def check_section(db: DBSession, section: WritingSection, llm: Optional[LLMClient] = None) -> Dict:
    """Feedback on the user's text. Never rewrites it."""
    text = (section.user_text or "").strip()
    if word_count(text) < 20:
        raise WritingError("Write at least a few sentences first, then check the section.")
    papers = list_session_papers(db, section.session_id)
    refs = reference_numbers(papers)
    by_n = {n: p for p in papers for n in [refs[p.id]]}
    cited = cited_numbers(text)
    unknown = [n for n in cited if n not in by_n]

    vec = await EmbeddingService().generate_embedding(text[:6000])
    hits = VectorStoreService(db).search(section.session_id, vec, n_results=20)
    shown, blocks = set(), []
    for n in [n for n in cited if n in by_n][:10]:  # papers the user cited
        p = by_n[n]
        shown.add(n)
        blocks.append(f"[{n}] {p.title}\n{(p.abstract or (p.full_text or '')[:800])[:800]}")
    for h in hits:  # other relevant papers they might cite
        n = refs.get(h["paper_id"])
        if n and n not in shown and len(shown) < 16:
            shown.add(n)
            blocks.append(f"[{n}] {by_n[n].title}\n{h['text'][:600]}")

    points = "\n".join(f"- {p['text']}" for p in (section.guidance or {}).get("points", [])) or "(none)"
    prompt = f"""TASK: check_section
You are a careful academic supervisor giving FEEDBACK on a researcher's draft section.
Do NOT rewrite their text and do NOT write replacement sentences. Point out issues only.

Section heading: {section.heading}
Points the section was meant to cover:
{points}

Their draft (citations are [n] numbers):
\"\"\"{text}\"\"\"

Papers (the ones they cited, plus other relevant ones):
{chr(10).join(blocks)}

Return JSON with:
- "uncited_claims": factual claims with no citation: {{"sentence": quote a few words, "suggested_refs": [n], "why": "..."}}
- "citation_issues": citations that do not support the sentence: {{"sentence": "...", "ref": n, "issue": "..."}}
- "missing_points": guide points or important findings not yet covered (short phrases)
- "strengths": 1-3 things done well
- "summary": 2 sentences of overall feedback
Only use paper numbers listed above."""
    data = await (llm or LLMClient()).complete_json(prompt, max_tokens=1500)
    allowed = set(shown)
    feedback = {
        "uncited_claims": [{"sentence": str(c.get("sentence", "")),
                            "suggested_refs": _clean_refs(c.get("suggested_refs"), allowed),
                            "why": str(c.get("why", ""))}
                           for c in data.get("uncited_claims") or [] if isinstance(c, dict)][:8],
        "citation_issues": [{"sentence": str(c.get("sentence", "")), "ref": c.get("ref"),
                             "issue": str(c.get("issue", ""))}
                            for c in data.get("citation_issues") or []
                            if isinstance(c, dict) and c.get("ref") in allowed][:8],
        "missing_points": [str(m) for m in data.get("missing_points") or []][:6],
        "strengths": [str(s) for s in data.get("strengths") or []][:3],
        "summary": str(data.get("summary", "")),
        "unknown_refs": unknown,
        "words": word_count(text),
        "target_words": (section.guidance or {}).get("target_words"),
    }
    section.feedback = feedback
    db.commit()
    return feedback


def compile_review(db: DBSession, session_id: int, default_title: str) -> Dict:
    """The user's own writing as a review dict (used by export_service.format_review)."""
    sections = []
    for s in list_sections(db, session_id):
        paras = [p.strip() for p in re.split(r"\n\s*\n", s.user_text or "") if p.strip()]
        if paras:
            sections.append({"heading": s.heading, "paragraphs": paras})
    return {"title": get_title(db, session_id, default_title), "sections": sections}
