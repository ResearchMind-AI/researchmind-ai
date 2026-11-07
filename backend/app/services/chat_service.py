"""
RAG chat over a session's papers, with validated citations.

Citations use the session's reference numbers [n] (the same numbers shown in
the Papers tab and the exported bibliography). After the answer is generated,
any [n] that does not point to a retrieved source is removed, so the model
cannot cite papers it was not shown.
"""
import re
from dataclasses import dataclass, field
from typing import AsyncIterator, Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from app.models.research import SessionMessage
from app.services.analysis_service import key_paper_ids, list_session_papers, reference_numbers
from app.services.embedding_service import EmbeddingService
from app.services.llm import LLMClient
from app.services.vector_store import VectorStoreService

SYSTEM = (
    "You are ResearchMind, a research assistant. Answer ONLY from the numbered sources "
    "provided. Cite every claim with the source number in square brackets, e.g. [3] or [2][5]. "
    "If the sources do not contain the answer, say so plainly and suggest what to search for. "
    "Be concise and precise; use short paragraphs or bullet points."
)
CITE_RE = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")


@dataclass
class ChatContext:
    question: str
    prompt: str
    history: List[Dict[str, str]]
    sources: List[Dict] = field(default_factory=list)  # [{"n", "paper_id", "title", "url", "year"}]
    gap_id: Optional[int] = None
    system: str = SYSTEM


def validate_citations(text: str, allowed: set) -> (str, List[int]):
    """Drop citation numbers not in `allowed`; return cleaned text and numbers actually cited."""
    cited: List[int] = []

    def repl(m: re.Match) -> str:
        nums = [int(x) for x in re.split(r"\s*[,;]\s*", m.group(1))]
        keep = [n for n in nums if n in allowed]
        for n in keep:
            if n not in cited:
                cited.append(n)
        return "".join(f"[{n}]" for n in keep)

    cleaned = CITE_RE.sub(repl, text)
    cleaned = re.sub(r" +([.,;:])", r"\1", cleaned)
    return cleaned, cited


async def build_context(db: DBSession, session_id: int, question: str,
                        k_chunks: int = 8, per_paper: int = 2, gap=None) -> ChatContext:
    """Retrieve sources for a question. With `gap`, the chat is about that research gap:
    its evidence papers are retrieved first and the history is the gap's own thread."""
    papers = list_session_papers(db, session_id)
    refs = reference_numbers(papers)
    by_id = {p.id: p for p in papers}
    store = VectorStoreService(db)

    query = question if gap is None else f"{question}\n\nResearch gap: {gap.title}. {gap.description or ''}"
    q_vec = await EmbeddingService().generate_embedding(query)
    hits = []
    evidence = [i for i in (gap.evidence_paper_ids or []) if i in refs] if gap is not None else []
    if evidence:
        hits.extend(store.search(session_id, q_vec, n_results=4, paper_ids=evidence))
    key = key_paper_ids(papers)
    more = [h for h in store.search(session_id, q_vec, n_results=k_chunks * 3)
            if h["chunk_id"] not in {x["chunk_id"] for x in hits}]
    # Key papers get a small boost; removed papers are dropped below (not in refs).
    more.sort(key=lambda h: h["score"] + (0.05 if h["paper_id"] in key else 0), reverse=True)
    hits.extend(more)
    chosen, counts = [], {}
    for h in hits:
        if h["paper_id"] not in refs or counts.get(h["paper_id"], 0) >= per_paper:
            continue
        counts[h["paper_id"]] = counts.get(h["paper_id"], 0) + 1
        chosen.append(h)
        if len(chosen) >= k_chunks:
            break

    sources, blocks, seen = [], [], set()
    for h in chosen:
        n, p = refs[h["paper_id"]], by_id[h["paper_id"]]
        blocks.append(f"[{n}] {p.title} ({p.publication_date.year if p.publication_date else 'n.d.'})\n{h['text']}")
        if n not in seen:
            seen.add(n)
            sources.append({"n": n, "paper_id": p.id, "title": p.title, "url": p.url,
                            "year": p.publication_date.year if p.publication_date else None})

    thread = SessionMessage.gap_id.is_(None) if gap is None else SessionMessage.gap_id == gap.id
    history_rows = (db.query(SessionMessage).filter(SessionMessage.session_id == session_id, thread)
                    .order_by(SessionMessage.id.desc()).limit(6).all())
    history = [{"role": m.role, "content": m.content} for m in reversed(history_rows)]

    system = SYSTEM
    if gap is not None:
        system = SYSTEM + (
            f"\n\nThis conversation is about one research gap the researcher is exploring:\n"
            f"Gap: {gap.title}\nDescription: {gap.description or '(none)'}\n"
            f"Research question: {gap.research_question or '(not set)'}\n"
            f"Researcher's notes: {gap.notes or '(none)'}\n"
            "Help them examine whether the gap is real, how to scope it, possible methods, data and "
            "risks. Be critical: say when the sources suggest the gap is already partly addressed.")

    if blocks:
        prompt = ("Sources:\n\n" + "\n\n---\n\n".join(blocks) +
                  f"\n\nQuestion: {question}\n\nAnswer using only the sources above, with [n] citations.")
    else:
        prompt = (f"Question: {question}\n\nThere are no papers in this session yet. Tell the user to run "
                  "discovery or upload PDFs first.")
    return ChatContext(question=question, prompt=prompt, history=history, sources=sources,
                       gap_id=gap.id if gap is not None else None, system=system)


async def stream_answer(ctx: ChatContext) -> AsyncIterator[str]:
    async for piece in LLMClient().stream(ctx.prompt, system=ctx.system, history=ctx.history):
        yield piece


def save_exchange(db: DBSession, session_id: int, user_id: int, ctx: ChatContext, raw_answer: str) -> Dict:
    allowed = {s["n"] for s in ctx.sources}
    answer, cited = validate_citations(raw_answer, allowed)
    cited_sources = [s for s in ctx.sources if s["n"] in cited]
    db.add(SessionMessage(session_id=session_id, author_id=user_id, role="user", content=ctx.question,
                          gap_id=ctx.gap_id))
    db.add(SessionMessage(session_id=session_id, author_id=None, role="assistant", content=answer,
                          citations=cited_sources, gap_id=ctx.gap_id))
    db.commit()
    return {"answer": answer, "citations": cited_sources}


async def answer_question(db: DBSession, session_id: int, user_id: int, question: str, gap=None) -> Dict:
    """Non-streaming helper used by the API."""
    ctx = await build_context(db, session_id, question, gap=gap)
    parts = [p async for p in stream_answer(ctx)]
    return save_exchange(db, session_id, user_id, ctx, "".join(parts))
