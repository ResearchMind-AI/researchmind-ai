"""Full text: finding legal copies, downloading safely, extracting pages, and the session pipeline."""
import asyncio

import httpx
import pytest
import respx

from tests.test_web import client_for, events


def _pdf(pages):
    import fitz
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(40, 40, 560, 800), text, fontsize=9)
    return doc.tobytes()


BODY = "Methods. We studied clinical decision support in emergency departments with a large cohort. " * 15


def test_extract_pages_drops_reference_list():
    from app.services.fulltext_service import extract_pages
    data = _pdf([f"Introduction. As shown in the references below, this matters.\n{BODY}", f"Results.\n{BODY}",
                 f"Discussion.\n{BODY}\nReferences\n1. Smith J. Something. 2020.\n2. Doe A. Else. 2021."])
    pages = extract_pages(data)
    assert len(pages) == 3 and "Results." in pages[1]
    assert "Discussion." in pages[2] and "Smith J." not in pages[2]
    # a 'References' line early in the paper is not mistaken for the reference list
    early = extract_pages(_pdf([f"References\nsee below\n{BODY}", BODY, BODY]))
    assert len(early) == 3


@respx.mock
def test_download_rejects_non_pdf_and_huge_files():
    from app.services.fulltext_service import NoFullText, download_pdf
    respx.get("https://pub.example/landing").mock(return_value=httpx.Response(200, text="<html>Buy access</html>"))
    respx.get("https://pub.example/huge.pdf").mock(return_value=httpx.Response(200, content=b"%PDF-1.4",
                                                    headers={"content-length": str(50 * 1024 * 1024)}))
    respx.get("https://pub.example/blocked.pdf").mock(return_value=httpx.Response(403))
    respx.get("https://pub.example/ok.pdf").mock(return_value=httpx.Response(200, content=_pdf([BODY])))
    for url, msg in [("landing", "Not a PDF"), ("huge.pdf", "20 MB"), ("blocked.pdf", "HTTP 403")]:
        with pytest.raises(NoFullText, match=msg):
            asyncio.run(download_pdf(f"https://pub.example/{url}"))
    assert asyncio.run(download_pdf("https://pub.example/ok.pdf")).startswith(b"%PDF")


@respx.mock
def test_finds_legal_copies_in_order(db, monkeypatch):
    from app.config import settings
    from app.models.paper import Paper, PaperSource
    from app.services import fulltext_service as ft
    monkeypatch.setattr(settings, "OFFLINE_DEMO", False)
    monkeypatch.setattr(settings, "OPENALEX_EMAIL", "me@example.com")
    doi = "10.1000/xyz.1"
    respx.get(url__startswith=f"https://api.openalex.org/works/https://doi.org/{doi}").mock(return_value=httpx.Response(
        200, json={"best_oa_location": {"pdf_url": "https://repo.example/a.pdf"}, "oa_locations": []}))
    respx.get(url__startswith=f"https://api.unpaywall.org/v2/{doi}").mock(return_value=httpx.Response(
        200, json={"best_oa_location": {"url_for_pdf": "https://pmc.example/b.pdf"},
                   "oa_locations": [{"url_for_pdf": "https://repo.example/a.pdf"}]}))
    p = Paper(id=5, title="T", doi=doi, source=PaperSource.OPENALEX, source_id="w1")
    assert asyncio.run(ft.candidate_urls(p)) == [("openalex", "https://repo.example/a.pdf"), ("unpaywall", "https://pmc.example/b.pdf")]
    arx = Paper(id=6, title="A", doi="10.48550/arXiv.2401.01234v2", source=PaperSource.OPENALEX, source_id="w2")
    urls = asyncio.run(ft.candidate_urls(arx))
    assert urls[0] == ("arxiv", "https://arxiv.org/pdf/2401.01234")

    # the first copy is a publisher page; the second is a real PDF
    respx.get("https://repo.example/a.pdf").mock(return_value=httpx.Response(200, text="<html>login</html>"))
    respx.get("https://pmc.example/b.pdf").mock(return_value=httpx.Response(200, content=_pdf([BODY, BODY])))
    src, pages = asyncio.run(ft.get_full_text(p))
    assert src == "unpaywall" and len(pages) == 2
    none = Paper(id=7, title="N", doi=None, source=PaperSource.PUBMED, source_id="1")
    with pytest.raises(ft.NoFullText):
        asyncio.run(ft.get_full_text(none))


def test_session_pipeline_offline(db):
    owner = client_for("ft@x.com")
    s = owner.post("/api/v1/research/sessions", json={"topic": "LLMs for clinical decision support"}).json()
    base = f"/api/v1/research/sessions/{s['id']}"
    ev = events(owner.post(f"{base}/analyse/stream", json={"max_papers": 10}))
    assert any("Full text for" in e.get("message", "") for e in ev) and ev[-1]["type"] == "done"
    papers = owner.get(f"{base}/papers").json()
    with_text = [p for p in papers if p["full_text"]]
    assert 0 < len(with_text) < len(papers)
    assert all(p["pages"] == 4 and p["full_text_source"] == "offline" for p in with_text)
    assert all(p["full_text_tried"] for p in papers)

    from app.models.research import PaperChunk
    chunks = db.query(PaperChunk).filter(PaperChunk.paper_id == with_text[0]["id"]).all()
    assert any("(p. 2)" in c.text for c in chunks)

    # nothing is retried automatically; retry=true tries the rest again
    ev = events(owner.post(f"{base}/fulltext/stream"))
    assert ev[-1] == {"type": "done", "tried": 0, "found": 0, "with_full_text": len(with_text), "kept": len(papers)}
    ev = events(owner.post(f"{base}/fulltext/stream", params={"retry": "true"}))
    assert ev[-1]["tried"] == len(papers) - len(with_text) and ev[-1]["found"] == 0

    # removed papers are skipped
    no_text = next(p for p in papers if not p["full_text"])
    owner.patch(f"{base}/papers/{no_text['id']}", json={"status": "removed"})
    ev = events(owner.post(f"{base}/fulltext/stream", params={"retry": "true"}))
    assert ev[-1]["tried"] == len(papers) - len(with_text) - 1 and ev[-1]["kept"] == len(papers) - 1
