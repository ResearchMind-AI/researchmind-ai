"""
Full text from legal open-access copies.

For each kept paper without full text, look for a free, legal PDF, in this order:
arXiv (always free), OpenAlex's open-access link, then Unpaywall by DOI. Download it
within limits, extract the text page by page with PyMuPDF (dropping the reference
list), and embed it with page markers so answers can point to pages, e.g. "[3] (p. 7)".

Only the extracted text is kept, never the PDF. Papers without a free copy, or whose
publisher blocks automated downloads, stay "abstract only"; the researcher can upload
the PDF themselves. Each paper is tried once; "Try again" in Papers retries the rest.
"""
import asyncio
import logging
import re
from typing import Callable, Dict, List, Optional, Tuple

import httpx
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.models.paper import Paper, PaperSource, SessionPaper
from app.services.http_utils import USER_AGENT, fetch

logger = logging.getLogger(__name__)

MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 60
DOWNLOAD_TIMEOUT = 30.0
CONCURRENCY = 4
MAX_PER_RUN = 40
MIN_TEXT = 1500
MAX_CHUNKS = 160  # passages per paper (a 60-page paper fits)  # characters; less than this is probably a scanned PDF or a landing page

REFS_RE = re.compile(r"^\s*(references|bibliography|literature cited|works cited)\s*:?\s*$", re.I | re.M)


class NoFullText(Exception):
    pass


# ── Finding a legal copy ─────────────────────────────────────────────────────

def _arxiv_id(p: Paper) -> Optional[str]:
    if p.source == PaperSource.ARXIV and p.source_id:
        return p.source_id
    m = re.match(r"^10\.48550/arxiv\.(.+)$", p.doi or "", re.I)
    if m:
        return m.group(1)
    m = re.search(r"arxiv\.org/abs/([\w.\-/]+)", p.url or "")
    return m.group(1) if m else None


async def candidate_urls(p: Paper) -> List[Tuple[str, str]]:
    """(source, pdf_url) pairs to try, best first."""
    out: List[Tuple[str, str]] = []
    aid = _arxiv_id(p)
    if aid:
        out.append(("arxiv", "https://arxiv.org/pdf/" + re.sub(r"v\d+$", "", aid)))
    if p.doi:
        params = {"mailto": settings.OPENALEX_EMAIL} if settings.OPENALEX_EMAIL else {}
        if settings.OPENALEX_API_KEY:
            params["api_key"] = settings.OPENALEX_API_KEY
        try:
            work = await fetch("openalex", f"https://api.openalex.org/works/https://doi.org/{p.doi}",
                               params=params, rate_per_sec=settings.OPENALEX_RATE_LIMIT, attempts=2)
            for loc in [work.get("best_oa_location") or {}] + (work.get("oa_locations") or []):
                if loc.get("pdf_url"):
                    out.append(("openalex", loc["pdf_url"]))
        except Exception as e:
            logger.info(f"OpenAlex OA lookup failed for {p.doi}: {e}")
        email = settings.OPENALEX_EMAIL or settings.CROSSREF_EMAIL or settings.PUBMED_EMAIL
        if email:  # Unpaywall requires an email address
            try:
                data = await fetch("unpaywall", f"https://api.unpaywall.org/v2/{p.doi}", params={"email": email},
                                   rate_per_sec=5, attempts=2)
                for loc in [data.get("best_oa_location") or {}] + (data.get("oa_locations") or []):
                    if loc.get("url_for_pdf"):
                        out.append(("unpaywall", loc["url_for_pdf"]))
            except Exception as e:
                logger.info(f"Unpaywall lookup failed for {p.doi}: {e}")
    seen, uniq = set(), []
    for src, url in out:
        if url not in seen:
            seen.add(url)
            uniq.append((src, url))
    return uniq


async def download_pdf(url: str) -> bytes:
    """Download with a size cap and timeout; refuse anything that isn't a PDF."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/pdf"}
    async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True, headers=headers) as client:
        async with client.stream("GET", url) as r:
            if r.status_code != 200:
                raise NoFullText(f"HTTP {r.status_code}")
            size = int(r.headers.get("content-length") or 0)
            if size > MAX_BYTES:
                raise NoFullText("PDF is larger than 20 MB")
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > MAX_BYTES:
                    raise NoFullText("PDF is larger than 20 MB")
    if not bytes(buf[:1024]).lstrip().startswith(b"%PDF"):
        raise NoFullText("Not a PDF (probably a publisher page)")
    return bytes(buf)


# ── Text extraction ──────────────────────────────────────────────────────────

def extract_pages(data: bytes, max_pages: int = MAX_PAGES) -> List[str]:
    """Text of each page, one page at a time (keeps memory low), reference list removed."""
    import fitz
    pages: List[str] = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pages.append(page.get_text("text") or "")
    return strip_references(pages)


def strip_references(pages: List[str]) -> List[str]:
    """Drop everything from a 'References' heading onwards, if it's in the back part of the paper."""
    if not pages:
        return pages
    total = sum(len(p) for p in pages)
    seen = 0
    for i, text in enumerate(pages):
        m = REFS_RE.search(text)
        if m and (seen + m.start()) > 0.4 * total:
            return pages[:i] + ([text[:m.start()]] if text[:m.start()].strip() else [])
        seen += len(text)
    return pages


PAGE_SEP = "\f"  # pages are stored joined by form feeds, so page numbers survive


def paged_chunks(p: Paper, pages: List[str], embedder) -> List[str]:
    """Passages to embed: the title and abstract, then each page split into passages that
    all start with their page marker, e.g. "(p. 7) ...", so any passage can be cited by page."""
    out = embedder.chunk_text(f"Title: {p.title}\n\nAbstract: {p.abstract or ''}")
    for i, text in enumerate(pages):
        flat = " ".join(text.split())
        if flat:
            out.extend(f"(p. {i + 1}) {c}" for c in embedder.chunk_text(flat))
    return out


def _offline_pages(p: Paper) -> List[str]:
    """OFFLINE_DEMO: about half of the papers 'have' a free copy, so the pipeline runs without network."""
    if p.id % 2:
        raise NoFullText("No free copy found (offline demo)")
    return [f"FAKE FULL TEXT page {n} of '{p.title}'. Methods: retrospective cohort of {100 + n * 10} patients. "
            f"Results: accuracy {70 + n}% on held-out cases. " * 12 for n in range(1, 5)]


# ── Running it for a session ─────────────────────────────────────────────────

async def get_full_text(p: Paper) -> Tuple[str, List[str]]:
    if settings.OFFLINE_DEMO:
        return "offline", _offline_pages(p)
    reasons = []
    for src, url in await candidate_urls(p):
        try:
            pages = extract_pages(await download_pdf(url))
            if sum(len(x) for x in pages) < MIN_TEXT:
                raise NoFullText("almost no text (scanned PDF?)")
            return src, pages
        except Exception as e:
            reasons.append(f"{src}: {e}")
    raise NoFullText("; ".join(reasons) or "No free copy found")


async def fetch_full_texts(db: DBSession, session_id: int, progress: Optional[Callable[[str], None]] = None,
                           retry: bool = False) -> Dict:
    """Get full text for kept papers that don't have it yet. Returns counts."""
    from app.services.embedding_service import EmbeddingService
    from app.services.vector_store import VectorStoreService
    say = progress or (lambda m: None)
    rows = (db.query(Paper).join(SessionPaper, SessionPaper.paper_id == Paper.id)
            .filter(SessionPaper.session_id == session_id, SessionPaper.status == "kept")
            .order_by(SessionPaper.is_key.desc(), SessionPaper.ref_no).all())
    def needs(p: Paper) -> bool:
        extra = p.extra_metadata or {}
        if p.full_text:  # fetched before every passage carried its page: fetch once more
            return extra.get("full_text_source") in ("arxiv", "openalex", "unpaywall", "offline") and not extra.get("paged_v2")
        return retry or not extra.get("full_text_tried")
    todo = [p for p in rows if needs(p)][:MAX_PER_RUN]
    kept_with_text = sum(1 for p in rows if p.full_text and p not in todo)
    if not todo:
        return {"tried": 0, "found": 0, "with_full_text": kept_with_text, "kept": len(rows)}

    say(f"Getting full texts for {len(todo)} papers…")
    sem = asyncio.Semaphore(CONCURRENCY)
    results: Dict[int, Tuple[Optional[str], Optional[List[str]], Optional[str]]] = {}
    done = 0

    async def one(p: Paper):
        nonlocal done
        async with sem:
            try:
                src, pages = await get_full_text(p)
                results[p.id] = (src, pages, None)
            except Exception as e:
                results[p.id] = (None, None, str(e)[:300])
            done += 1
            if done % 5 == 0 or done == len(todo):
                say(f"Full text: checked {done} of {len(todo)}…")

    await asyncio.gather(*(one(p) for p in todo))

    embedder, store, found = EmbeddingService(), VectorStoreService(db), 0
    for p in todo:
        src, pages, err = results[p.id]
        extra = dict(p.extra_metadata or {})
        extra["full_text_tried"] = True
        if pages:
            p.full_text = PAGE_SEP.join(pages)
            extra.update({"full_text_source": src, "pages": len(pages), "paged_v2": True})
            extra.pop("full_text_error", None)
            chunks = paged_chunks(p, pages, embedder)[:MAX_CHUNKS]
            vectors = await embedder.generate_embeddings_batch(chunks)
            await store.add_paper_embeddings(session_id, p.id, chunks, vectors)
            found += 1
        else:
            extra["full_text_error"] = err
        p.extra_metadata = extra
        db.commit()
    total = kept_with_text + found
    say(f"Full text for {total} of {len(rows)} kept papers.")
    return {"tried": len(todo), "found": found, "with_full_text": total, "kept": len(rows)}
