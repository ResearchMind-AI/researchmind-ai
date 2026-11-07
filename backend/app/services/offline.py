"""
OFFLINE TEST MODE (OFFLINE_DEMO=true): fake paper sources, embeddings and LLM.

Used by automated tests and for checking the UI without network access or
API keys. Output is clearly fake and must never be shown as real research.
"""
import hashlib
import json
import math
import re
from types import SimpleNamespace
from typing import List, Optional

from app.models.paper import PaperSource
from app.schemas.paper import PaperSearchResult

DIM = 128
_TOPICS = [
    ("retrieval-augmented generation", "grounding language model answers in retrieved documents"),
    ("clinical decision support", "machine learning models that assist clinicians at the bedside"),
    ("evaluation benchmarks", "measuring factual accuracy and hallucination rates"),
    ("knowledge graphs", "structured representations that link entities and relations"),
    ("low-resource settings", "deploying models in hospitals with limited data and compute"),
]


def _vec(text: str) -> List[float]:
    v = [0.0] * DIM
    for tok in re.findall(r"[a-z]{3,}", text.lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        v[h % DIM] += 1.0 if (h >> 8) % 2 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class FakeEmbeddings:
    def __init__(self):
        self.embeddings = self

    async def create(self, input, model=None):
        items = [input] if isinstance(input, str) else input
        return SimpleNamespace(data=[SimpleNamespace(embedding=_vec(t)) for t in items])


class FakeSource:
    def __init__(self, name: str, label: str, source: PaperSource, mode: str = "limited"):
        self.name, self.label, self.source, self.mode = name, label, source, mode
        self.default_max_results = 12

    async def search(self, query: str, max_results: Optional[int] = None,
                     start_year: Optional[int] = None, end_year: Optional[int] = None):
        out = []
        for i in range(max_results or self.default_max_results):
            theme, desc = _TOPICS[i % len(_TOPICS)]
            year = 2018 + (i % 7)
            out.append(PaperSearchResult(
                title=f"[FAKE] {theme.title()} for {query[:40]} — {self.label} study {i + 1}",
                abstract=f"FAKE ABSTRACT for offline testing. This study examines {theme}: {desc}. "
                         f"It reports results on {query}. Sample size {50 + i * 10}.",
                authors=[f"Alex Tester{i}", f"Sam Example{i % 3}"],
                publication_date=f"{year}-0{1 + i % 9}-15",
                journal="Journal of Offline Testing",
                doi=f"10.0000/fake.{self.name}.{i}" if i % 4 else None,
                source=self.source, source_id=f"{self.name}-{i}",
                url=f"https://example.org/{self.name}/{i}", citations_count=(i * 7) % 90,
            ))
        return out

    async def get_by_doi(self, doi: str):
        if "unknown" in doi:
            return None
        r = (await self.search("offline doi"))[1]
        r.title, r.doi, r.source_id = f"[FAKE] Paper added by DOI {doi}", doi, f"doi-{doi}"
        return r

    async def recommendations(self, paper_id: str, limit: int = 10):
        return []

    async def get_by_id(self, source_id: str):
        return (await self.search("offline"))[0]


def fake_sources():
    return {
        "openalex": FakeSource("openalex", "OpenAlex", PaperSource.OPENALEX),
        "semantic_scholar": FakeSource("semantic_scholar", "Semantic Scholar", PaperSource.SEMANTIC_SCHOLAR),
        "pubmed": FakeSource("pubmed", "PubMed", PaperSource.PUBMED),
        "arxiv": FakeSource("arxiv", "arXiv", PaperSource.ARXIV, mode="full"),
    }


class FakeLLM:
    async def complete(self, prompt: str, system: str = "") -> str:
        task = re.search(r"TASK: (\w+)", prompt)
        task = task.group(1) if task else "chat"
        ids = [int(x) for x in re.findall(r"\[id=(\d+)\]", prompt)]
        nums = sorted({int(x) for x in re.findall(r"^\[(\d+)\]", prompt, re.M)})
        if task == "plan_queries":
            topic = re.search(r'"(.+?)"', prompt).group(1)
            return json.dumps({"domain": "biomedical", "queries": [topic, f"{topic} methods", f"{topic} evaluation"]})
        if task == "name_themes":
            clusters = re.findall(r"## Cluster (\d+)[^\n]*\n((?:.|\n)*?)(?=\n## Cluster|\Z)", prompt)
            themes = []
            for cid, body in clusters:
                cids = [int(x) for x in re.findall(r"\[id=(\d+)\]", body)]
                themes.append({"cluster": int(cid), "label": f"Fake theme {int(cid) + 1}",
                               "summary": "FAKE summary generated in offline test mode.",
                               "key_findings": [f"Fake finding (id={cids[0]})"] if cids else [],
                               "key_paper_ids": cids[:2]})
            return json.dumps({"overview": "FAKE overview (offline test mode).", "themes": themes})
        if task == "find_gaps":
            return json.dumps({"gaps": [
                {"title": f"Fake gap {i + 1}", "gap_type": "method",
                 "description": "FAKE gap description (offline test mode).",
                 "evidence_paper_ids": ids[i:i + 2] + [999999], "research_question": "Fake question?",
                 "confidence": "low"} for i in range(3)]})
        if task == "lit_review":
            a, b = (nums + [1, 2])[:2]
            return json.dumps({"title": "Fake Literature Review", "sections": [
                {"heading": "Introduction", "paragraphs": [f"FAKE intro sentence [{a}]. Another claim [{b}][999]."]},
                {"heading": "Conclusion", "paragraphs": [f"FAKE conclusion [{a}, {b}]."]}]})
        if task == "writing_outline":
            a, b = (nums + [1, 2])[:2]
            extra = " (leads with key papers)" if "[KEY PAPER]" in prompt else ""
            extra += " (positions against closest work)" if "Novelty check:" in prompt else ""
            mk = lambda h, k, w: {"heading": h, "kind": k, "points": [{"text": f"Fake point for {h}{extra}", "refs": [a, 999]}],
                                  "agreements": [f"Studies agree [{a}][{b}]"], "disagreements": [],
                                  "questions": ["What is the fake question?"], "target_words": w}
            return json.dumps({"title": "Fake Review Title", "sections": [
                mk("Introduction", "intro", 250), mk("Fake theme section", "theme", 450),
                mk("Gaps and future directions", "gaps", 300), mk("Conclusion", "conclusion", 200)]})
        if task == "check_section":
            first = nums[0] if nums else 1
            return json.dumps({"uncited_claims": [{"sentence": "Fake claim", "suggested_refs": [first, 999],
                                                   "why": "needs a source"}],
                               "citation_issues": [], "missing_points": ["Fake missing point"],
                               "strengths": ["Clear structure"], "summary": "FAKE feedback (offline)."})
        if task == "gap_evidence":
            first = nums[0] if nums else 1
            return json.dumps({"supporting": [{"n": first, "why": "fake support"}, {"n": 999, "why": "bad"}],
                               "contradicting": [], "summary": "FAKE evidence summary.",
                               "research_question": "Fake research question?"})
        if task == "novelty_check":
            return json.dumps({"verdict": "partially_addressed", "explanation": "FAKE novelty explanation.",
                               "closest": [{"index": 0, "why": "fake closest"}, {"index": 99, "why": "bad"}]})
        if task == "paper_metadata":
            return json.dumps({"title": "Fake Uploaded Paper", "authors": ["Up Loader"], "year": 2024,
                               "abstract": "FAKE abstract extracted from upload."})
        first = nums[0] if nums else 1
        return f"FAKE ANSWER (offline test mode). The sources discuss this [{first}] and more [99]."
