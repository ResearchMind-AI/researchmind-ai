"""
Semantic Scholar Academic Graph API (free).

Without SEMANTIC_SCHOLAR_API_KEY: shared public pool, slow and sometimes
refused when busy, so we ask for fewer papers and back off.
With a free key: dedicated rate limit, more papers, and recommendations
("papers like this one") to find related work the keyword search missed.
"""
import logging
from typing import List, Optional

from app.config import settings
from app.models.paper import PaperSource
from app.schemas.paper import PaperSearchResult
from app.services.http_utils import fetch

logger = logging.getLogger(__name__)

S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_RECS_URL = "https://api.semanticscholar.org/recommendations/v1/papers/forpaper/{paper_id}"
FIELDS = "title,abstract,authors,year,venue,externalIds,citationCount,url,publicationDate"


class SemanticScholarService:
    name = "semantic_scholar"
    label = "Semantic Scholar"

    def __init__(self):
        self.api_key = settings.SEMANTIC_SCHOLAR_API_KEY

    @property
    def mode(self) -> str:
        return "full" if self.api_key else "limited"

    @property
    def default_max_results(self) -> int:
        return 50 if self.api_key else 20

    @property
    def _headers(self) -> dict:
        return {"x-api-key": self.api_key} if self.api_key else {}

    @property
    def _rate(self) -> float:
        return settings.SEMANTIC_SCHOLAR_RATE_LIMIT if self.api_key else 0.5

    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None,
    ) -> List[PaperSearchResult]:
        params = {"query": query, "limit": min(max_results or self.default_max_results, 100),
                  "fields": FIELDS}
        if start_year or end_year:
            params["year"] = f"{start_year or ''}-{end_year or ''}"
        data = await fetch(self.name, S2_SEARCH_URL, params=params, headers=self._headers,
                           rate_per_sec=self._rate, attempts=4 if self.api_key else 3)
        papers = [p for p in (self._parse(item) for item in data.get("data") or []) if p]
        logger.info(f"Semantic Scholar ({self.mode}): {len(papers)} papers for '{query}'")
        return papers

    async def recommendations(self, paper_id: str, limit: int = 10) -> List[PaperSearchResult]:
        """Papers similar to the given one. Only used in full mode (needs a key)."""
        if not self.api_key:
            return []
        data = await fetch(self.name, S2_RECS_URL.format(paper_id=paper_id),
                           params={"limit": limit, "fields": FIELDS},
                           headers=self._headers, rate_per_sec=self._rate)
        return [p for p in (self._parse(item) for item in data.get("recommendedPapers") or []) if p]

    async def get_by_id(self, paper_id: str) -> Optional[PaperSearchResult]:
        try:
            item = await fetch(self.name, f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}",
                               params={"fields": FIELDS}, headers=self._headers, rate_per_sec=self._rate)
            return self._parse(item)
        except Exception as e:
            logger.error(f"Semantic Scholar lookup failed for {paper_id}: {e}")
            return None

    @staticmethod
    def _parse(item: dict) -> Optional[PaperSearchResult]:
        if not item or not item.get("paperId") or not item.get("title"):
            return None
        ext = item.get("externalIds") or {}
        doi = ext.get("DOI")
        pub_date = item.get("publicationDate") or (str(item["year"]) if item.get("year") else None)
        return PaperSearchResult(
            title=item["title"],
            abstract=item.get("abstract"),
            authors=[a.get("name") for a in item.get("authors") or [] if a.get("name")] or None,
            publication_date=pub_date,
            journal=item.get("venue") or None,
            doi=doi,
            source=PaperSource.SEMANTIC_SCHOLAR,
            source_id=item["paperId"],
            url=item.get("url") or (f"https://doi.org/{doi}" if doi else None),
            citations_count=item.get("citationCount") or 0,
        )
