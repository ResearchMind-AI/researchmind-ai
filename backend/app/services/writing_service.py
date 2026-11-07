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
    out = []
    for n in items or []:
        if isinstance(n, str) and n.strip().strip("[]").isdigit():
            n = int(n.strip().strip("[]"))
        if isinstance(n, int) and n in allowed and n not in out:
            out.append(n)
    return out


def _guide_context(db: DBSession, session_id: int, papers, refs: Dict[int, int]) -> str:
    """Themes, tracked gaps (with novelty checks and notes), key papers and paper notes."""
    from app.services.analysis_service import key_paper_ids
    from app.services.links_service import gap_brief, tracked_gaps
    analysis = get_artifact(db, session_id, "analysis") or {}
    themes = analysis.get("themes") or []
    tracked = tracked_gaps(db, session_id)
    if not tracked:
        tracked = db.query(Gap).filter(Gap.session_id == session_id, Gap.status != "dropped").order_by(Gap.id).limit(4).all()
    key = key_paper_ids(papers)
    theme_text = "\n".join(
        f"- {t['label']}: {t['summary']} Papers: " + ", ".join(f"[{refs[i]}]" for i in t["paper_ids"][:12] if i in refs)
        for t in themes) or "(no themes yet: infer them from the papers)"
    gap_text = "\n".join(gap_brief(g) for g in tracked) or "(none)"
    def line(p):
        note = getattr(getattr(p, "session_link", None), "notes", None)
        star = " [KEY PAPER]" if p.id in key else ""
        return (f"[{refs[p.id]}]{star} {p.title} ({p.publication_date.year if p.publication_date else 'n.d.'})\n"
                f"{(p.abstract or (p.full_text or '')[:500] or '')[:500]}" + (f"\nResearcher's note: {note[:300]}" if note else ""))
    ordered = sorted(papers, key=lambda p: (p.id not in key, refs[p.id]))[:45]
    return f"""Themes:
{theme_text}

Research gaps they are tracking (with novelty checks; where recent work partly covers a gap,
the guide should say how to position the gap against it):
{gap_text}

Papers (refer to them only by bracket number). Papers marked KEY PAPER are the researcher's
own picks: lead with them where they fit. Respect their notes.
{chr(10).join(line(p) for p in ordered)}"""


def _guidance_from(sec: Dict, allowed: set) -> Dict:
    return {
        "points": [pt for pt in (_parse_point(p, allowed) for p in sec.get("points") or []) if pt][:6],
        "agreements": [str(a) for a in sec.get("agreements") or []][:3],
        "disagreements": [str(d) for d in sec.get("disagreements") or []][:3],
        "questions": [str(q) for q in sec.get("questions") or []][:3],
        "target_words": int(sec["target_words"]) if str(sec.get("target_words", "")).isdigit() else None,
    }


def _save_basis(db: DBSession, session_id: int) -> None:
    from app.services.links_service import basis
    meta = dict(get_artifact(db, session_id, "writing_meta") or {})
    meta["basis"] = basis(db, session_id)
    save_artifact(db, session_id, "writing_meta", meta)


def guidance_changes(db: DBSession, session_id: int) -> Optional[Dict]:
    from app.services.links_service import basis, changes_since, describe
    if not list_sections(db, session_id):
        return None
    ch = changes_since((get_artifact(db, session_id, "writing_meta") or {}).get("basis"), basis(db, session_id))
    return {**ch, "summary": describe(ch)} if ch else None


async def refresh_guidance(db: DBSession, session_id: int, topic: str,
                           llm: Optional[LLMClient] = None) -> Dict:
    """Update the suggested points for the user's CURRENT outline. Headings, order and the
    user's text are untouched. Returns what changed, for the 'Guide updated' note."""
    sections = list_sections(db, session_id)
    if not sections:
        raise WritingError("There is no outline yet.")
    changes = guidance_changes(db, session_id) or {}
    papers = list_session_papers(db, session_id)
    if not papers:
        raise WritingError("Keep at least one paper first.")
    refs = reference_numbers(papers)
    allowed = set(refs.values())
    outline = "\n".join(f"{i + 1}. {s.heading} ({s.kind})" for i, s in enumerate(sections))
    prompt = f"""TASK: writing_outline
A researcher is WRITING their own literature review on: "{topic}"
Do not write the review. Update their writing guide for the outline they already have.

Their outline (keep exactly these sections, in this order):
{outline}

{_guide_context(db, session_id, papers, refs)}

For each section give "points" (3-6 short phrases with "refs"), "agreements", "disagreements",
"questions" and "target_words", as in a writing guide.
Return JSON: {{"sections": [{{"heading": "...", "points": [{{"text": "...", "refs": [3]}}],
"agreements": [], "disagreements": [], "questions": [], "target_words": 400}}]}}"""
    data = await (llm or LLMClient()).complete_json(prompt, max_tokens=4000)
    got = [s for s in data.get("sections") or [] if isinstance(s, dict)]
    by_heading = {str(s.get("heading", "")).strip().lower(): s for s in got}
    for i, sec in enumerate(sections):
        new = by_heading.get(sec.heading.strip().lower()) or (got[i] if i < len(got) else None)
        if new:
            sec.guidance = _guidance_from(new, allowed)
    db.commit()
    _save_basis(db, session_id)
    return changes


def _parse_point(p, allowed: set) -> Optional[Dict]:
    """Points may come back as {"text", "refs"} or as plain strings like "Accuracy varies [14][29]"."""
    if isinstance(p, dict):
        text = p.get("text") or p.get("point") or p.get("description") or ""
        refs = p.get("refs") or p.get("references") or p.get("papers") or []
    elif isinstance(p, str):
        text, refs = p, []
    else:
        return None
    text = str(text).strip()
    inline = [int(x) for x in re.findall(r"\[(\d+)\]", text)]
    text = re.sub(r"\s*(\[\d+\])+\s*", " ", text).strip().rstrip(" ,;")
    if not text:
        return None
    return {"text": text, "refs": _clean_refs(list(refs) + inline, allowed)}


async def generate_outline(db: DBSession, session_id: int, topic: str,
                           llm: Optional[LLMClient] = None) -> List[WritingSection]:
    """Create or refresh section guidance. The user's text is never deleted."""
    papers = list_session_papers(db, session_id)
    if not papers:
        raise WritingError("Add papers to the session first.")
    refs = reference_numbers(papers)
    allowed = set(refs.values())
    ctx = _guide_context(db, session_id, papers, refs)
    prompt = f"""TASK: writing_outline
A researcher is WRITING their own literature review on: "{topic}"
Do not write the review. Give them a writing guide.

{ctx}

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
        guidance = _guidance_from(sec, allowed)
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
    _save_basis(db, session_id)
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
    every = {p.session_ref: p for p in list_session_papers(db, section.session_id, include_removed=True)}
    removed = [n for n in cited if n not in by_n and n in every]
    unknown = [n for n in cited if n not in by_n and n not in every]

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
        "removed_refs": [{"n": n, "title": every[n].title,
                          "reason": every[n].session_link.removed_reason} for n in removed],
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
