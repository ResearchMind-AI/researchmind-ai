"""
Themes and gap analysis for a session.

Themes: papers are clustered on their embeddings (k-means), then the LLM names
and summarises each cluster. Clustering first makes themes consistent and
cheaper than asking an LLM to invent them from scratch.

Gaps: the LLM reads the themes plus the abstracts and must name specific
under-explored combinations, each backed by real paper IDs from the session.
Every paper ID the LLM returns is checked against the session.
"""
import logging
from collections import Counter
from typing import Dict, List, Optional

import numpy as np
from sqlalchemy.orm import Session as DBSession

from app.models.knowledge_map import KnowledgeNode, NodeRelationship, NodeType
from app.models.paper import Paper, SessionPaper
from app.services.discovery_service import get_artifact, save_artifact
from app.services.llm import LLMClient
from app.services.vector_store import VectorStoreService

logger = logging.getLogger(__name__)


def list_session_papers(db: DBSession, session_id: int, include_removed: bool = False) -> List[Paper]:
    """Session papers in citation-number order. Removed papers are left out unless asked for,
    so themes, gaps, chat and the writing guide only ever see the papers the researcher kept."""
    q = (db.query(Paper, SessionPaper)
         .join(SessionPaper, SessionPaper.paper_id == Paper.id)
         .filter(SessionPaper.session_id == session_id))
    if not include_removed:
        q = q.filter(SessionPaper.status == "kept")
    rows = q.order_by(SessionPaper.ref_no.asc().nullslast(), SessionPaper.id).all()
    out = []
    for p, sp in rows:
        # Per-session details ride along on the (shared) Paper object for this request.
        p.session_ref = sp.ref_no
        p.session_link = sp
        out.append(p)
    return out


def reference_numbers(papers: List[Paper]) -> Dict[int, int]:
    """paper_id -> the paper's fixed citation number [n] in this session."""
    return {p.id: (getattr(p, "session_ref", None) or i + 1) for i, p in enumerate(papers)}


def key_paper_ids(papers: List[Paper]) -> set:
    return {p.id for p in papers if getattr(getattr(p, "session_link", None), "is_key", False)}


def _year(p: Paper) -> Optional[int]:
    return p.publication_date.year if p.publication_date else None


def _paper_line(p: Paper, chars: int = 600) -> str:
    year = _year(p) or "n.d."
    abstract = (p.abstract or (p.full_text or "")[:chars] or "No abstract.")[:chars]
    return f"[id={p.id}] {p.title} ({year})\n{abstract}"


def choose_k(n: int) -> int:
    if n < 4:
        return 1
    return int(min(7, max(2, round((n / 2) ** 0.5))))


def cluster_papers(vectors: Dict[int, np.ndarray]) -> Dict[int, List[int]]:
    """Group paper ids by k-means on normalised embeddings, ordered by closeness to centroid."""
    ids = list(vectors.keys())
    if not ids:
        return {}
    k = choose_k(len(ids))
    if k == 1:
        return {0: ids}
    from sklearn.cluster import KMeans

    X = np.array([vectors[i] for i in ids], dtype=np.float32)
    X = X / np.clip(np.linalg.norm(X, axis=1, keepdims=True), 1e-9, None)
    km = KMeans(n_clusters=k, n_init=10, random_state=42).fit(X)
    clusters: Dict[int, List[int]] = {}
    dists = np.linalg.norm(X - km.cluster_centers_[km.labels_], axis=1)
    for idx in np.argsort(dists):
        clusters.setdefault(int(km.labels_[idx]), []).append(ids[idx])
    # Order clusters largest first, renumber 0..k-1
    ordered = sorted(clusters.values(), key=len, reverse=True)
    return {i: c for i, c in enumerate(ordered)}


async def generate_themes(db: DBSession, session_id: int, topic: str,
                          llm: Optional[LLMClient] = None) -> Dict:
    llm = llm or LLMClient()
    papers = {p.id: p for p in list_session_papers(db, session_id)}
    store = VectorStoreService(db)
    vectors = {pid: v for pid, v in store.paper_vectors(session_id).items() if pid in papers}
    if not vectors:
        return {"overview": "", "themes": [], "error": "No embedded papers in this session yet."}

    clusters = cluster_papers(vectors)
    blocks = []
    for cid, pids in clusters.items():
        sample = "\n\n".join(_paper_line(papers[pid], 500) for pid in pids[:8])
        blocks.append(f"## Cluster {cid} ({len(pids)} papers)\n{sample}")

    prompt = f"""TASK: name_themes
Research topic: "{topic}"

The session's papers have been grouped into clusters by semantic similarity.
For EACH cluster, write:
- "cluster": the cluster number
- "label": a specific theme name (3-7 words, not generic like "Various studies")
- "summary": 2-4 sentences on what this body of work studies and how
- "key_findings": 2-4 concrete findings or claims, each ending with the supporting paper ids like (id=12, id=40)
- "key_paper_ids": up to 4 ids of the most representative papers in that cluster

Also write "overview": 3-4 sentences describing the overall research landscape across clusters.
Use ONLY information in the abstracts. Use ONLY paper ids shown.

{chr(10).join(blocks)}

Return JSON: {{"overview": "...", "themes": [{{"cluster": 0, "label": "...", "summary": "...",
"key_findings": ["..."], "key_paper_ids": [1, 2]}}]}}"""

    data = await llm.complete_json(prompt, max_tokens=3500)
    by_cluster = {int(t.get("cluster", -1)): t for t in data.get("themes", []) if isinstance(t, dict)}

    themes = []
    for cid, pids in clusters.items():
        t = by_cluster.get(cid, {})
        members = [papers[p] for p in pids]
        authors = Counter(a for p in members for a in (p.authors or [])[:6])
        years = [y for y in (_year(p) for p in members) if y]
        key_ids = [i for i in (t.get("key_paper_ids") or []) if isinstance(i, int) and i in pids][:4]
        themes.append({
            "label": t.get("label") or f"Theme {cid + 1}",
            "summary": t.get("summary", ""),
            "key_findings": [f for f in (t.get("key_findings") or []) if isinstance(f, str)][:4],
            "key_paper_ids": key_ids or pids[:3],
            "paper_ids": pids,
            "top_authors": [a for a, _ in authors.most_common(5)],
            "year_range": [min(years), max(years)] if years else None,
            "size": len(pids),
        })

    result = {"overview": data.get("overview", ""), "themes": themes}
    _mirror_nodes(db, session_id, NodeType.CONCEPT, [
        {"label": t["label"], "summary": t["summary"], "paper_ids": t["paper_ids"],
         "importance": t["size"] / max(1, len(vectors)), "keywords": t["top_authors"]} for t in themes])
    from app.services.links_service import basis
    result["basis"] = basis(db, session_id)
    analysis = get_artifact(db, session_id, "analysis") or {}
    analysis.update(result)
    save_artifact(db, session_id, "analysis", analysis)
    return result


async def generate_gaps(db: DBSession, session_id: int, topic: str,
                        llm: Optional[LLMClient] = None) -> List[Dict]:
    llm = llm or LLMClient()
    papers = list_session_papers(db, session_id)
    valid = {p.id for p in papers}
    analysis = get_artifact(db, session_id, "analysis") or {}
    themes = analysis.get("themes") or []
    theme_text = "\n".join(f"- {t['label']}: {t['summary']}" for t in themes) or "(themes not generated)"
    paper_text = "\n\n".join(_paper_line(p, 400) for p in papers[:45])
    from app.models.research import Gap
    kept = db.query(Gap).filter(Gap.session_id == session_id,
                                (Gap.pinned.is_(True)) | (Gap.source == "user")).all()
    kept_text = "\n".join(f"- {g.title}" for g in kept) or "(none)"

    prompt = f"""TASK: find_gaps
Research topic: "{topic}"

Themes in the literature:
{theme_text}

Gaps the researcher is already tracking (do NOT repeat these):
{kept_text}

Papers (abstracts):
{paper_text}

Identify 3-5 research gaps: specific, under-explored areas a researcher could pursue.
Good gaps are concrete: a method not yet applied to a population or setting, two themes
that are never combined, contradictory findings nobody has resolved, an outdated evidence
base, or missing evaluation in real-world conditions. Do NOT write vague gaps like
"more research is needed".

For each gap return:
- "title": short name (5-10 words)
- "gap_type": one of method, population, setting, contradiction, recency, evaluation, combination
- "description": 2-3 sentences explaining what is missing and why it matters
- "evidence_paper_ids": 2-4 paper ids whose content shows the gap (from the list above only)
- "research_question": one concrete research question that would address it
- "confidence": "high", "medium" or "low", given these are abstracts only

Return JSON: {{"gaps": [{{"title": "...", "gap_type": "...", "description": "...",
"evidence_paper_ids": [1], "research_question": "...", "confidence": "medium"}}]}}"""

    data = await llm.complete_json(prompt, max_tokens=2500)
    gaps = []
    for g in data.get("gaps", [])[:5]:
        if not isinstance(g, dict) or not g.get("title"):
            continue
        g["evidence_paper_ids"] = [i for i in g.get("evidence_paper_ids") or []
                                   if isinstance(i, int) and i in valid][:4]
        gaps.append(g)

    _mirror_nodes(db, session_id, NodeType.GAP, [
        {"label": g["title"][:200], "summary": g.get("description"), "paper_ids": g["evidence_paper_ids"],
         "importance": {"high": 0.9, "medium": 0.6, "low": 0.3}.get(g.get("confidence"), 0.5),
         "keywords": [g.get("gap_type", "")]} for g in gaps])
    analysis = get_artifact(db, session_id, "analysis") or {}
    analysis["gaps"] = gaps
    save_artifact(db, session_id, "analysis", analysis)
    from app.services.gaps_service import save_ai_gaps
    save_ai_gaps(db, session_id, gaps)
    return gaps


def _mirror_nodes(db: DBSession, session_id: int, node_type: NodeType, items: List[Dict]) -> None:
    """Keep the knowledge_nodes table (used by the /knowledge-map API) in sync."""
    old = db.query(KnowledgeNode).filter(KnowledgeNode.session_id == session_id,
                                         KnowledgeNode.node_type == node_type).all()
    old_ids = [n.id for n in old]
    if old_ids:
        db.query(NodeRelationship).filter(
            (NodeRelationship.source_node_id.in_(old_ids)) | (NodeRelationship.target_node_id.in_(old_ids))
        ).delete(synchronize_session=False)
        for n in old:
            db.delete(n)
    for it in items:
        db.add(KnowledgeNode(session_id=session_id, label=it["label"], description=it.get("summary"),
                             node_type=node_type, importance_score=float(it.get("importance", 0.5)),
                             paper_ids=it.get("paper_ids", []), citation_count=len(it.get("paper_ids", [])),
                             summary=it.get("summary"), keywords=it.get("keywords", [])))
    db.commit()
