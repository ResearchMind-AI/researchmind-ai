"""
Literature review export (DOCX / PDF) with formatted citations.

1. The LLM drafts a structured review from the session's themes, gaps and
   abstracts, citing papers with the session reference numbers [n].
2. Citations are validated (unknown numbers dropped) and the draft is saved.
3. The draft is rendered with in-text citations and a bibliography in the
   chosen style: APA 7 (author-date, alphabetical) or IEEE (numbered in order
   of first citation). Rendering is pure Python: python-docx and ReportLab.
"""
import io
import re
from datetime import date
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session as DBSession

from app.models.paper import Paper
from app.services.analysis_service import list_session_papers, reference_numbers
from app.services.chat_service import CITE_RE, validate_citations
from app.services.discovery_service import get_artifact, save_artifact
from app.services.llm import LLMClient

STYLES = ("APA", "IEEE")
DISCLAIMER = ("AI-generated draft from paper abstracts. Check every claim against the "
              "original papers before using it.")


# ── Draft ────────────────────────────────────────────────────────────────────

async def draft_review(db: DBSession, session_id: int, topic: str,
                       llm: Optional[LLMClient] = None) -> Dict:
    papers = list_session_papers(db, session_id)
    if not papers:
        raise ValueError("This session has no papers yet.")
    refs = reference_numbers(papers)
    analysis = get_artifact(db, session_id, "analysis") or {}
    themes = analysis.get("themes") or []
    gaps = analysis.get("gaps") or []

    theme_text = "\n".join(
        f"- {t['label']}: {t['summary']} Papers: " + ", ".join(f"[{refs[i]}]" for i in t["paper_ids"][:10] if i in refs)
        for t in themes) or "(not generated; infer themes from the papers)"
    gap_text = "\n".join(f"- {g['title']}: {g.get('description', '')}" for g in gaps) or "(not generated)"
    paper_text = "\n\n".join(
        f"[{refs[p.id]}] {p.title} ({p.publication_date.year if p.publication_date else 'n.d.'})\n"
        f"{(p.abstract or (p.full_text or '')[:700] or '')[:700]}" for p in papers[:45])

    prompt = f"""TASK: lit_review
Write a structured literature review on: "{topic}"

Themes:
{theme_text}

Research gaps:
{gap_text}

Papers (cite them ONLY with their bracket numbers, e.g. [3] or [3][7]):
{paper_text}

Structure:
1. "Introduction" - scope and why the topic matters (1-2 paragraphs)
2. One section per theme, with a specific heading (2-3 paragraphs each), synthesising and
   comparing studies rather than listing them one by one
3. "Research Gaps and Future Directions" (1-2 paragraphs)
4. "Conclusion" (1 paragraph)

Rules: academic tone; every factual sentence cites at least one paper; use only facts in the
abstracts; never invent numbers or papers.

Return JSON: {{"title": "...", "sections": [{{"heading": "...", "paragraphs": ["...", "..."]}}]}}"""

    data = await (llm or LLMClient()).complete_json(prompt, max_tokens=6000)
    allowed = set(refs.values())
    sections = []
    for s in data.get("sections", []):
        if not isinstance(s, dict):
            continue
        paras = [validate_citations(p, allowed)[0] for p in s.get("paragraphs", []) if isinstance(p, str)]
        if paras:
            sections.append({"heading": s.get("heading", ""), "paragraphs": paras})
    review = {"title": data.get("title") or f"Literature Review: {topic}", "topic": topic,
              "sections": sections, "generated": date.today().isoformat()}
    save_artifact(db, session_id, "lit_review", review)
    return review


# ── Citation formatting ──────────────────────────────────────────────────────

def _split_name(name: str) -> Tuple[str, str]:
    """'Jane A. Smith' -> ('Smith', 'J. A.'); 'Smith, Jane' -> ('Smith', 'J.')"""
    name = " ".join(name.split())
    if "," in name:
        last, first = [x.strip() for x in name.split(",", 1)]
    else:
        parts = name.split(" ")
        if len(parts) >= 2 and re.fullmatch(r"[A-Z]{1,3}\.?", parts[-1]):
            # "Zhou Z" / "Smith JA": surname first, initials last
            letters = parts[-1].rstrip(".")
            return " ".join(parts[:-1]), " ".join(f"{c}." for c in letters)
        last, first = parts[-1], " ".join(parts[:-1])
    initials = " ".join(f"{p[0]}." for p in re.split(r"[\s\-]+", first) if p)
    return last, initials


def _year(p: Paper) -> str:
    return str(p.publication_date.year) if p.publication_date else "n.d."


def _apa_who(p: Paper) -> str:
    authors = p.authors or []
    if not authors:
        return p.title.split(":")[0][:40]
    last = [_split_name(a)[0] for a in authors]
    if len(last) == 1:
        return last[0]
    if len(last) == 2:
        return f"{last[0]} & {last[1]}"
    return f"{last[0]} et al."


def apa_in_text(p: Paper, year: Optional[str] = None) -> str:
    return f"{_apa_who(p)}, {year or _year(p)}"


def _end_title(title: str) -> str:
    """Title followed by a full stop, unless it already ends with . ? or !"""
    title = title.strip()
    return title if title[-1:] in ".?!" else title + "."


def apa_reference(p: Paper, year: Optional[str] = None) -> str:
    year = year or _year(p)
    names = [f"{l}, {i}".strip().rstrip(",") for l, i in (_split_name(a) for a in (p.authors or []))]
    if len(names) > 20:
        names = names[:19] + ["…"] + names[-1:]
    if len(names) >= 2:
        author_str = ", ".join(names[:-1]) + ", & " + names[-1]
    else:
        author_str = names[0] if names else ""
    title = _end_title(p.title)
    parts = [f"{author_str} ({year}). {title}" if author_str else f"{title} ({year})."]
    if p.journal:
        parts.append(f"{p.journal}.")
    if p.doi:
        parts.append(f"https://doi.org/{p.doi}")
    elif p.url:
        parts.append(p.url)
    return " ".join(parts)


def ieee_reference(p: Paper, n: int) -> str:
    names = [f"{i} {l}".strip() for l, i in (_split_name(a) for a in (p.authors or []))]
    if len(names) > 6:
        author_str = f"{names[0]} et al."
    elif len(names) > 1:
        author_str = ", ".join(names[:-1]) + ", and " + names[-1]
    else:
        author_str = names[0] if names else ""
    title = p.title.strip().rstrip(".")
    quoted = f"\u201c{title}\u201d" if title[-1:] in "?!" else f"\u201c{title},\u201d"
    bits = [f"[{n}]", f"{author_str}," if author_str else "", quoted]
    if p.journal:
        bits.append(f"{p.journal},")
    bits.append(f"{_year(p)}" + ("," if p.doi else "."))
    if p.doi:
        bits.append(f"doi: {p.doi}.")
    return " ".join(b for b in bits if b)


def apa_year_labels(papers: List[Paper]) -> Dict[int, str]:
    """APA disambiguation: same author(s) and year -> 2024a, 2024b (ordered by title)."""
    groups: Dict[Tuple[str, str], List[Paper]] = {}
    for p in papers:
        groups.setdefault((_apa_who(p).lower(), _year(p)), []).append(p)
    labels = {}
    for (_, year), members in groups.items():
        if len(members) == 1:
            labels[members[0].id] = year
            continue
        for i, p in enumerate(sorted(members, key=lambda x: x.title.lower())):
            labels[p.id] = f"{year}{chr(ord('a') + i)}" if year != "n.d." else f"n.d.-{chr(ord('a') + i)}"
    return labels


# A citation group like [3] or [3][7] or [3, 7], optionally already wrapped in
# parentheses by the model, e.g. "([3][7])", so we never output "((...))".
GROUP_RE = re.compile(r"\(\s*((?:\[\d+(?:\s*[,;]\s*\d+)*\]\s*)+)\)|((?:\[\d+(?:\s*[,;]\s*\d+)*\])+)")


def format_review(review: Dict, papers: List[Paper], style: str = "APA") -> Dict:
    """Apply a citation style. Returns {"title", "sections", "references": [str]}."""
    style = style.upper()
    refs = reference_numbers(papers)
    by_n = {n: p for p, n in ((p, refs[p.id]) for p in papers)}
    order: List[int] = []
    for s in review["sections"]:
        for para in s["paragraphs"]:
            for m in CITE_RE.finditer(para):
                for x in re.split(r"\s*[,;]\s*", m.group(1)):
                    n = int(x)
                    if n in by_n and n not in order:
                        order.append(n)
    ieee_num = {n: i + 1 for i, n in enumerate(order)}
    years = apa_year_labels([by_n[n] for n in order])

    def render(para: str) -> str:
        def repl(m: re.Match) -> str:
            group = m.group(1) or m.group(2)
            nums = []
            for x in re.findall(r"\d+", group):
                if int(x) in by_n and int(x) not in nums:
                    nums.append(int(x))
            if not nums:
                return ""
            if style == "IEEE":
                return "[" + ", ".join(str(ieee_num[n]) for n in nums) + "]"
            inner = "; ".join(apa_in_text(by_n[n], years[by_n[n].id]) for n in nums)
            before = m.string[:m.start()]
            inside_parens = m.group(2) is not None and before.count("(") > before.count(")")
            return inner if inside_parens else f"({inner})"
        out = GROUP_RE.sub(repl, para)
        return re.sub(r" +([.,;:])", r"\1", out)

    sections = [{"heading": s["heading"], "paragraphs": [render(p) for p in s["paragraphs"]]}
                for s in review["sections"]]
    if style == "IEEE":
        references = [ieee_reference(by_n[n], ieee_num[n]) for n in order]
    else:
        references = sorted((apa_reference(by_n[n], years[by_n[n].id]) for n in order),
                            key=lambda r: r.lower())
    return {"title": review["title"], "topic": review.get("topic", ""), "sections": sections,
            "references": references, "style": style}


# ── Renderers ────────────────────────────────────────────────────────────────

def to_docx(doc_data: Dict) -> bytes:
    from docx import Document
    from docx.shared import Pt, Inches

    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(11)
    doc.add_heading(doc_data["title"], level=0)
    meta = doc.add_paragraph()
    meta.add_run(f"{doc_data.get('byline', 'Generated by ResearchMind AI')} on {date.today():%d %B %Y} · "
                 f"Citation style: {doc_data['style']}").italic = True
    if doc_data.get("note", DISCLAIMER):
        note = doc.add_paragraph()
        note.add_run(doc_data.get("note", DISCLAIMER)).italic = True
    for s in doc_data["sections"]:
        doc.add_heading(s["heading"], level=1)
        for para in s["paragraphs"]:
            doc.add_paragraph(para)
    doc.add_heading("References", level=1)
    for ref in doc_data["references"]:
        p = doc.add_paragraph(ref)
        if doc_data["style"] == "APA":
            p.paragraph_format.left_indent = Inches(0.5)
            p.paragraph_format.first_line_indent = Inches(-0.5)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def to_pdf(doc_data: Dict) -> bytes:
    from xml.sax.saxutils import escape
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2.2 * cm, rightMargin=2.2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm, title=doc_data["title"])
    ss = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=ss["BodyText"], fontSize=10.5, leading=15, spaceAfter=8)
    ref_style = ParagraphStyle("ref", parent=body, leftIndent=18 if doc_data["style"] == "APA" else 0,
                               firstLineIndent=-18 if doc_data["style"] == "APA" else 0, fontSize=9.5)
    meta = ParagraphStyle("meta", parent=body, textColor="#555555", fontSize=9)
    story = [Paragraph(escape(doc_data["title"]), ss["Title"]),
             Paragraph(escape(f"{doc_data.get('byline', 'Generated by ResearchMind AI')} on "
                              f"{date.today():%d %B %Y} · Citation style: {doc_data['style']}"), meta)]
    if doc_data.get("note", DISCLAIMER):
        story.append(Paragraph(escape(doc_data.get("note", DISCLAIMER)), meta))
    story.append(Spacer(1, 10))
    for s in doc_data["sections"]:
        story.append(Paragraph(escape(s["heading"]), ss["Heading2"]))
        story.extend(Paragraph(escape(p), body) for p in s["paragraphs"])
    story.append(Paragraph("References", ss["Heading2"]))
    story.extend(Paragraph(escape(r), ref_style) for r in doc_data["references"])
    pdf.build(story)
    return buf.getvalue()


def render(db: DBSession, session_id: int, review: Dict, style: str, fmt: str,
           user_written: bool = False) -> bytes:
    data = format_review(review, list_session_papers(db, session_id, include_removed=True), style)
    if user_written:
        data["byline"], data["note"] = "Prepared with ResearchMind AI", None
    return to_docx(data) if fmt == "docx" else to_pdf(data)
