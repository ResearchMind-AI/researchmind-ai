"""
Paper discovery pipeline: topic -> papers stored and embedded in a session.

1. Plan: the LLM classifies the topic's domain and rewrites it into search queries.
2. Route: OpenAlex + Semantic Scholar always; PubMed for biomedical topics;
   arXiv for computing / physics / maths topics.
3. Search all sources concurrently. A failing source is skipped, never fatal.
4. Full mode extras: Semantic Scholar recommendations (needs a key).
5. Deduplicate by DOI / normalised title, fill missing DOIs via Crossref.
6. Rank by semantic similarity to the topic (plus a small citation boost).
7. Store papers, link them to the session and save per-session embeddings.
"""
import asyncio
import logging
import math
import re
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.models.paper import Paper, PaperSource, SessionPaper
from app.models.research import SessionArtifact
from app.schemas.paper import PaperSearchResult
from app.services.arxiv_service import ArxivService
from app.services.embedding_service import EmbeddingService
from app.services.http_utils import SourceUnavailable, fetch
from app.services.llm import LLMClient
from app.services.openalex_service import OpenAlexService
from app.services.pubmed_service import PubMedService
from app.services.semantic_scholar_service import SemanticScholarService
from app.services.vector_store import VectorStoreService, cosine_scores

logger = logging.getLogger(__name__)

Progress = Optional[Callable[[str], None]]

BIOMEDICAL_HINTS = {"clinical", "patient", "disease", "cancer", "medical", "health", "drug",
                    "therapy", "gene", "protein", "cell", "neuro", "covid", "diabetes", "biolog",
                    "hospital", "nursing", "vaccine", "mental", "epidemi", "pharma", "surgery"}
COMPUTING_HINTS = {"learning", "neural", "algorithm", "llm", "language model", "transformer",
                   "computer", "software", "robot", "quantum", "physics", "math", "network",
                   "ai ", "artificial intelligence", "data", "vision", "retrieval", "graph"}


def all_sources():
    if settings.OFFLINE_DEMO:
        from app.services.offline import fake_sources
        return fake_sources()
    return {"openalex": OpenAlexService(), "semantic_scholar": SemanticScholarService(),
            "pubmed": PubMedService(), "arxiv": ArxivService()}


def source_status() -> List[Dict[str, str]]:
    """Which sources run in full vs limited mode (shown in the UI and /health)."""
    notes = {
        "openalex": ("OPENALEX_API_KEY", "~1,000 searches/day, 50 papers per query",
                     "~100 searches/day, 20 papers per query"),
        "semantic_scholar": ("SEMANTIC_SCHOLAR_API_KEY", "dedicated rate limit + recommendations",
                             "shared public pool (may be slow)"),
        "pubmed": ("PUBMED_API_KEY", "10 requests/sec", "3 requests/sec"),
        "arxiv": ("", "no key needed", "no key needed"),
    }
    out = []
    for name, src in all_sources().items():
        env, full, limited = notes.get(name, ("", "", ""))
        out.append({"name": name, "label": src.label, "mode": src.mode, "key": env,
                    "detail": full if src.mode == "full" else limited})
    return out


def parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(value[:len(datetime.now().strftime(fmt))], fmt)
        except ValueError:
            continue
    return None


def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (title or "").lower())[:120]


def heuristic_domain(topic: str) -> str:
    t = f" {topic.lower()} "
    if any(h in t for h in BIOMEDICAL_HINTS):
        return "biomedical"
    if any(h in t for h in COMPUTING_HINTS):
        return "computing"
    return "general"


async def plan_queries(topic: str, llm: Optional[LLMClient] = None) -> Tuple[str, List[str]]:
    """Ask the LLM for the topic's domain and 3 search queries (falls back to heuristics)."""
    prompt = f"""TASK: plan_queries
A researcher wants literature on this topic:
"{topic}"

1. Classify the domain as one of: biomedical, computing, physical, social, general.
   (biomedical = medicine, biology, health, neuroscience; computing = CS/AI/ML/maths;
   physical = physics, chemistry, engineering; social = social sciences, economics, education.)
2. Write 3 short keyword search queries (3-8 words each, no boolean operators) that together
   cover the topic: the core phrasing, a synonym-based variant, and a method/application variant.

Return JSON: {{"domain": "...", "queries": ["...", "...", "..."]}}"""
    try:
        data = await (llm or LLMClient()).complete_json(prompt, max_tokens=400)
        domain = str(data.get("domain", "")).lower().strip() or heuristic_domain(topic)
        queries = [q.strip() for q in data.get("queries", []) if isinstance(q, str) and q.strip()]
        return domain, (queries or [topic])[:3]
    except Exception as e:
        logger.warning(f"Query planning failed, using heuristics: {e}")
        return heuristic_domain(topic), [topic]


def pick_sources(domain: str) -> List[str]:
    chosen = ["openalex", "semantic_scholar"]
    if domain == "biomedical":
        chosen.append("pubmed")
    if domain in ("computing", "physical"):
        chosen.append("arxiv")
    return chosen


def dedupe(results: List[PaperSearchResult]) -> List[Dict]:
    """Merge duplicates found by different sources/queries."""
    merged: Dict[str, Dict] = {}
    doi_index: Dict[str, str] = {}
    for r in results:
        doi = (r.doi or "").lower().strip() or None
        key = doi_index.get(doi) if doi else None
        key = key or norm_title(r.title)
        if not key:
            continue
        if key in merged:
            m = merged[key]
            m["found_in"].add(r.source.value)
            if not m["result"].abstract and r.abstract:
                m["result"] = r.model_copy(update={"doi": m["result"].doi or r.doi})
            m["citations"] = max(m["citations"], r.citations_count or 0)
            if doi and not m["result"].doi:
                m["result"] = m["result"].model_copy(update={"doi": r.doi})
        else:
            merged[key] = {"result": r, "found_in": {r.source.value}, "citations": r.citations_count or 0}
        if doi:
            doi_index[doi] = key
    return list(merged.values())


async def fill_missing_dois(items: List[Dict], limit: int = 8) -> None:
    """Look up DOIs on Crossref (free) for top papers that lack one."""
    if settings.OFFLINE_DEMO:
        return
    todo = [it for it in items if not it["result"].doi and len(it["result"].title) > 20][:limit]
    for it in todo:
        params = {"query.bibliographic": it["result"].title, "rows": 1, "select": "DOI,title"}
        if settings.CROSSREF_EMAIL:
            params["mailto"] = settings.CROSSREF_EMAIL
        try:
            data = await fetch("crossref", "https://api.crossref.org/works", params=params,
                               rate_per_sec=5, attempts=2, timeout=15)
            hits = data.get("message", {}).get("items", [])
            if hits and hits[0].get("title") and \
                    norm_title(hits[0]["title"][0]) == norm_title(it["result"].title):
                it["result"] = it["result"].model_copy(update={"doi": hits[0]["DOI"]})
        except Exception as e:
            logger.debug(f"Crossref lookup failed: {e}")


def paper_document(r: PaperSearchResult) -> str:
    parts = [f"Title: {r.title}"]
    if r.abstract:
        parts.append(f"Abstract: {r.abstract}")
    return "\n\n".join(parts)


def upsert_paper(db: DBSession, r: PaperSearchResult) -> Paper:
    paper = None
    if r.doi:
        paper = db.query(Paper).filter(Paper.doi == r.doi).first()
    if not paper:
        paper = db.query(Paper).filter(Paper.source == r.source, Paper.source_id == r.source_id).first()
    if paper:
        if not paper.abstract and r.abstract:
            paper.abstract = r.abstract
        paper.citations_count = max(paper.citations_count or 0, r.citations_count or 0)
        return paper
    paper = Paper(
        title=r.title[:1000], abstract=r.abstract, authors=r.authors,
        publication_date=parse_date(r.publication_date), journal=(r.journal or None),
        doi=r.doi, source=r.source, source_id=r.source_id, url=r.url,
        citations_count=r.citations_count or 0, embedding_model=settings.EMBEDDING_MODEL,
    )
    db.add(paper)
    db.flush()
    return paper


def save_artifact(db: DBSession, session_id: int, kind: str, content: dict) -> None:
    row = db.query(SessionArtifact).filter(SessionArtifact.session_id == session_id,
                                           SessionArtifact.kind == kind).first()
    if row:
        row.content = content
        row.updated_at = datetime.now(timezone.utc)
    else:
        db.add(SessionArtifact(session_id=session_id, kind=kind, content=content))
    db.commit()


def get_artifact(db: DBSession, session_id: int, kind: str) -> Optional[dict]:
    row = db.query(SessionArtifact).filter(SessionArtifact.session_id == session_id,
                                           SessionArtifact.kind == kind).first()
    return row.content if row else None


async def discover_papers(
    db: DBSession,
    session_id: int,
    user_id: int,
    topic: str,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    max_papers: Optional[int] = None,
    progress: Progress = None,
) -> Dict:
    """Run discovery for a session. Returns stats for the UI."""
    say = progress or (lambda msg: None)
    max_papers = max_papers or settings.MAX_PAPERS_PER_SESSION
    llm, embedder = LLMClient(), EmbeddingService()
    sources = all_sources()

    say("Planning search queries…")
    domain, queries = await plan_queries(topic, llm)
    chosen = pick_sources(domain)

    say(f"Searching {', '.join(sources[s].label for s in chosen)}…")
    tasks, labels = [], []
    for name in chosen:
        src = sources[name]
        n_queries = len(queries) if src.mode == "full" else 1
        for q in queries[:n_queries]:
            tasks.append(src.search(q, None, start_year, end_year))
            labels.append((name, q))
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    status: Dict[str, Dict] = {n: {"label": sources[n].label, "mode": sources[n].mode,
                                   "found": 0, "errors": 0} for n in chosen}
    results: List[PaperSearchResult] = []
    for (name, _q), out in zip(labels, outcomes):
        if isinstance(out, Exception):
            status[name]["errors"] += 1
            logger.warning(f"{name} failed: {out}")
            continue
        status[name]["found"] += len(out)
        results.extend(out)

    s2 = sources["semantic_scholar"]
    if s2.mode == "full":
        seeds = [r for r in results if r.source == PaperSource.SEMANTIC_SCHOLAR][:3]
        recs = await asyncio.gather(*[s2.recommendations(r.source_id, 10) for r in seeds],
                                    return_exceptions=True)
        for out in recs:
            if not isinstance(out, Exception):
                results.extend(out)
                status["semantic_scholar"]["found"] += len(out)

    if not results:
        stats = {"topic": topic, "domain": domain, "queries": queries, "sources": status,
                 "candidates": 0, "added": 0, "error": "No papers found. All sources failed or "
                 "returned nothing — try again shortly or broaden the topic."}
        save_artifact(db, session_id, "discovery", stats)
        return stats

    say(f"Removing duplicates from {len(results)} results…")
    items = dedupe(results)
    await fill_missing_dois(items)

    say(f"Ranking {len(items)} unique papers by relevance…")
    docs = [paper_document(it["result"]) for it in items]
    chunk_lists = [embedder.chunk_text(d) for d in docs]
    flat = [c for cl in chunk_lists for c in cl]
    vectors = await embedder.generate_embeddings_batch(flat + [topic])
    topic_vec = np.array(vectors[-1], dtype=np.float32)
    pos, paper_vecs = 0, []
    for it, cl in zip(items, chunk_lists):
        it["chunks"] = cl
        it["embeddings"] = vectors[pos:pos + len(cl)]
        pos += len(cl)
        paper_vecs.append(np.mean(np.array(it["embeddings"], dtype=np.float32), axis=0))
    sims = cosine_scores(np.array(paper_vecs), topic_vec)
    max_cit = max((it["citations"] for it in items), default=0) or 1
    for it, sim in zip(items, sims):
        cit = math.log1p(it["citations"]) / math.log1p(max_cit)
        it["score"] = 0.85 * float(sim) + 0.10 * cit + (0.05 if it["result"].abstract else -0.05)
    items.sort(key=lambda x: x["score"], reverse=True)

    say("Saving papers and embeddings…")
    store = VectorStoreService(db)
    existing = {sp.paper_id for sp in db.query(SessionPaper).filter(SessionPaper.session_id == session_id)}
    added = 0
    for rank, it in enumerate(items):
        if added >= max_papers:
            break
        paper = upsert_paper(db, it["result"])
        if paper.id in existing:
            continue
        extra = dict(paper.extra_metadata or {})
        extra["found_in"] = sorted(it["found_in"] | set(extra.get("found_in", [])))
        paper.extra_metadata = extra
        db.add(SessionPaper(session_id=session_id, paper_id=paper.id, added_by_user_id=user_id,
                            relevance_score=max(1, 5 - rank // max(1, max_papers // 5))))
        db.flush()
        await store.add_paper_embeddings(session_id, paper.id, it["chunks"], it["embeddings"])
        paper.embedding_generated = True
        existing.add(paper.id)
        added += 1
    db.commit()

    stats = {"topic": topic, "domain": domain, "queries": queries, "sources": status,
             "candidates": len(items), "added": added, "total_in_session": len(existing),
             "ran_at": datetime.now(timezone.utc).isoformat()}
    save_artifact(db, session_id, "discovery", stats)
    say(f"Added {added} papers.")
    return stats
