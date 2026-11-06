"""End-to-end research loop in offline mode: discover -> themes -> gaps -> chat -> export -> upload."""
import asyncio
import io

import fitz
from docx import Document

from app.models.paper import SessionPaper
from app.models.research import PaperChunk, SessionMessage
from app.services.analysis_service import generate_gaps, generate_themes, list_session_papers
from app.services.chat_service import answer_question, validate_citations
from app.services.discovery_service import dedupe, discover_papers, get_artifact, parse_date
from app.services.export_service import apa_in_text, draft_review, format_review, render
from app.services.upload_service import add_uploaded_paper


def run(c):
    return asyncio.run(c)


def test_discovery_stores_papers_and_session_embeddings(db, make_user, make_session):
    u = make_user()
    s = make_session(u)
    stats = run(discover_papers(db, s.id, u.id, s.topic, max_papers=20))
    assert stats["added"] == 20 and stats["domain"] == "biomedical"
    assert set(stats["sources"]) == {"openalex", "semantic_scholar", "pubmed"}  # biomedical -> PubMed
    assert db.query(SessionPaper).filter_by(session_id=s.id).count() == 20
    assert db.query(PaperChunk).filter_by(session_id=s.id).count() >= 20
    assert get_artifact(db, s.id, "discovery")["added"] == 20


def test_reused_papers_are_embedded_for_new_session(db, make_user, make_session):
    """Regression: a paper already in the DB must still get embeddings in a new session."""
    u = make_user()
    s1, s2 = make_session(u), make_session(u)
    run(discover_papers(db, s1.id, u.id, s1.topic, max_papers=10))
    run(discover_papers(db, s2.id, u.id, s2.topic, max_papers=10))
    ids1 = {sp.paper_id for sp in db.query(SessionPaper).filter_by(session_id=s1.id)}
    ids2 = {sp.paper_id for sp in db.query(SessionPaper).filter_by(session_id=s2.id)}
    assert ids1 & ids2, "same papers should be reused"
    for pid in ids1 & ids2:
        assert db.query(PaperChunk).filter_by(session_id=s2.id, paper_id=pid).count() > 0


def test_themes_gaps_chat_export(db, make_user, make_session):
    u = make_user()
    s = make_session(u)
    run(discover_papers(db, s.id, u.id, s.topic, max_papers=20))
    session_ids = {p.id for p in list_session_papers(db, s.id)}

    themes = run(generate_themes(db, s.id, s.topic))["themes"]
    assert 2 <= len(themes) <= 7
    assert sum(t["size"] for t in themes) == 20
    assert all(set(t["key_paper_ids"]) <= session_ids for t in themes)

    gaps = run(generate_gaps(db, s.id, s.topic))
    assert len(gaps) == 3
    assert all(999999 not in g["evidence_paper_ids"] for g in gaps), "invented ids must be dropped"

    res = run(answer_question(db, s.id, u.id, "What evaluation benchmarks are used?"))
    assert "[99]" not in res["answer"], "citation to a source that was not retrieved must be removed"
    assert res["citations"] and db.query(SessionMessage).filter_by(session_id=s.id).count() == 2

    review = run(draft_review(db, s.id, s.topic))
    assert "[999]" not in str(review["sections"])
    papers = list_session_papers(db, s.id)
    apa = format_review(review, papers, "APA")
    ieee = format_review(review, papers, "IEEE")
    assert apa["references"] and "(" in apa["sections"][0]["paragraphs"][0]
    assert ieee["references"][0].startswith("[1]")
    assert "[1]" in ieee["sections"][0]["paragraphs"][0]

    docx_bytes = render(db, s.id, review, "APA", "docx")
    text = "\n".join(p.text for p in Document(io.BytesIO(docx_bytes)).paragraphs)
    assert "References" in text and review["title"] in text
    pdf_bytes = render(db, s.id, review, "IEEE", "pdf")
    assert pdf_bytes[:4] == b"%PDF"


def test_upload_pdf_adds_paper_with_embeddings(db, make_user, make_session):
    u = make_user()
    s = make_session(u)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "A study of retrieval augmented generation in hospitals. " * 3)
    for i in range(30):
        page.insert_text((72, 100 + i * 20), f"Line {i}: results show grounded answers reduce errors.")
    data = doc.tobytes()
    paper = run(add_uploaded_paper(db, s.id, u.id, "mine.pdf", data))
    assert paper.title == "Fake Uploaded Paper" and paper.full_text
    assert db.query(PaperChunk).filter_by(session_id=s.id, paper_id=paper.id).count() >= 1


def test_helpers():
    assert validate_citations("A [1] B [2, 7] C [9].", {1, 2}) == ("A [1] B [2] C.", [1, 2])
    assert parse_date("2021-03") .month == 3 and parse_date("2020").year == 2020 and parse_date("bad") is None

    class P:
        authors = ["Jane A. Smith", "Bob Lee", "C D"]
        publication_date = parse_date("2020-01-01")
        title = "T"
    assert apa_in_text(P) == "Smith et al., 2020"
    P.authors = ["Jane Smith", "Bob Lee"]
    assert apa_in_text(P) == "Smith & Lee, 2020"


def test_dedupe_merges_by_doi_and_title():
    from app.models.paper import PaperSource
    from app.schemas.paper import PaperSearchResult as R
    a = R(title="Same Paper", abstract=None, authors=None, publication_date=None, journal=None,
          doi="10.1/X", source=PaperSource.OPENALEX, source_id="1", url=None, citations_count=3)
    b = R(title="Same paper!", abstract="has abstract", authors=None, publication_date=None, journal=None,
          doi="10.1/x", source=PaperSource.PUBMED, source_id="2", url=None, citations_count=9)
    [m] = dedupe([a, b])
    assert m["result"].abstract == "has abstract" and m["citations"] == 9
    assert m["found_in"] == {"openalex", "pubmed"}


def test_citation_formatting_regressions():
    """Bugs seen on the live deployment: ((double parens)), same author+year, 'expertise?.'"""
    from types import SimpleNamespace as P
    papers = [
        P(id=1, title="Guideline-based CDSS with LLMs", authors=["Solène Delourme", "A Redjdal", "J Bouaud"],
          publication_date=parse_date("2024"), journal="Stud Health", doi="10.1/a", url=None),
        P(id=2, title="Breast cancer tumour boards and LLMs", authors=["Solène Delourme", "B Seroussi", "X Y"],
          publication_date=parse_date("2024"), journal="Stud Health", doi="10.1/b", url=None),
        P(id=3, title="Enhancing or replacing human expertise?", authors=["Jian Li", "Zhou Z"],
          publication_date=parse_date("2025"), journal="Intelligent Medicine", doi="10.1/c", url=None),
    ]
    review = {"title": "T", "sections": [{"heading": "H", "paragraphs": [
        "Boards benefit ([1][2]). Experts debate this [3]. Also (see [1])."]}]}
    apa = format_review(review, papers, "APA")
    para = apa["sections"][0]["paragraphs"][0]
    assert "((" not in para and "))" not in para
    assert "(Delourme et al., 2024b; Delourme et al., 2024a)" in para  # 'Boards…' < 'Guideline…' by title
    assert "(Li & Zhou, 2025)." in para
    assert "(see Delourme et al., 2024b)." in para  # already inside parentheses: no extra pair
    refs = apa["references"]
    assert any("(2024a). Breast cancer tumour boards and LLMs." in r for r in refs)
    assert any("(2024b). Guideline-based CDSS with LLMs." in r for r in refs)
    assert any("human expertise? Intelligent Medicine." in r for r in refs), refs
    assert not any("?." in r for r in refs)

    ieee = format_review(review, papers, "IEEE")
    p = ieee["sections"][0]["paragraphs"][0]
    assert "([" not in p and "Boards benefit [1, 2]." in p
    assert any("“Enhancing or replacing human expertise?”" in r for r in ieee["references"])
