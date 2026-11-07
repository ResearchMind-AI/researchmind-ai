"""
OpenAlex API integration service (free).

Without OPENALEX_API_KEY: about $0.10/day of free usage (~100 searches).
With a free key: about $1/day (~1,000 searches), so we fetch more per query.
"""
import logging
from typing import List, Optional

from app.config import settings
from app.models.paper import PaperSource
from app.schemas.paper import PaperSearchResult
from app.services.http_utils import fetch

logger = logging.getLogger(__name__)

OPENALEX_API_URL = "https://api.openalex.org/works"
SELECT_FIELDS = ("id,title,abstract_inverted_index,authorships,publication_date,"
                 "primary_location,doi,cited_by_count")


class OpenAlexService:
    """Service for interacting with OpenAlex API"""

    name = "openalex"
    label = "OpenAlex"

    def __init__(self):
        self.api_key = settings.OPENALEX_API_KEY

    @property
    def mode(self) -> str:
        return "full" if self.api_key else "limited"

    @property
    def default_max_results(self) -> int:
        return 50 if self.api_key else 20

    def _base_params(self) -> dict:
        params = {}
        if self.api_key:
            params["api_key"] = self.api_key
        if settings.OPENALEX_EMAIL:
            params["mailto"] = settings.OPENALEX_EMAIL
        return params

    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None,
    ) -> List[PaperSearchResult]:
        """Search OpenAlex; raises SourceUnavailable if the API keeps failing."""
        filters = ["has_abstract:true"]
        if start_year:
            filters.append(f"from_publication_date:{start_year}-01-01")
        if end_year:
            filters.append(f"to_publication_date:{end_year}-12-31")

        params = {
            **self._base_params(),
            "search": query,
            "per-page": min(max_results or self.default_max_results, 100),
            "select": SELECT_FIELDS,
            "filter": ",".join(filters),
        }
        data = await fetch(self.name, OPENALEX_API_URL, params=params,
                           rate_per_sec=settings.OPENALEX_RATE_LIMIT)
        papers = [p for p in (self._parse_openalex_work(w) for w in data.get("results", [])) if p]
        logger.info(f"OpenAlex ({self.mode}): {len(papers)} papers for '{query}'")
        return papers

    async def search_papers(self, query: str, max_results: int = 20,
                            start_year: Optional[int] = None,
                            end_year: Optional[int] = None) -> List[PaperSearchResult]:
        """Backwards-compatible search used by the /papers/search endpoint (never raises)."""
        try:
            return await self.search(query, max_results, start_year, end_year)
        except Exception as e:
            logger.error(f"Error searching OpenAlex: {e}")
            return []

    def _parse_openalex_work(self, work: dict) -> Optional[PaperSearchResult]:
        try:
            openalex_id = (work.get("id") or "").replace("https://openalex.org/", "")
            if not openalex_id or not work.get("title"):
                return None

            authors = [a.get("author", {}).get("display_name")
                       for a in work.get("authorships") or []]
            authors = [a for a in authors if a]

            journal = None
            loc = work.get("primary_location") or {}
            if loc.get("source"):
                journal = loc["source"].get("display_name")

            doi = work.get("doi")
            if doi:
                doi = doi.replace("https://doi.org/", "")

            return PaperSearchResult(
                title=work["title"],
                abstract=self._reconstruct_abstract(work.get("abstract_inverted_index")),
                authors=authors or None,
                publication_date=work.get("publication_date"),
                journal=journal,
                doi=doi,
                source=PaperSource.OPENALEX,
                source_id=openalex_id,
                url=f"https://doi.org/{doi}" if doi else work.get("id"),
                citations_count=work.get("cited_by_count", 0) or 0,
            )
        except Exception as e:
            logger.error(f"Error parsing OpenAlex work: {e}")
            return None

    @staticmethod
    def _reconstruct_abstract(inverted_index: Optional[dict]) -> Optional[str]:
        """Rebuild abstract text from OpenAlex's inverted index."""
        if not inverted_index:
            return None
        try:
            max_pos = max(max(p) for p in inverted_index.values())
            words = [""] * (max_pos + 1)
            for word, positions in inverted_index.items():
                for pos in positions:
                    words[pos] = word
            text = " ".join(w for w in words if w).strip()
            return text or None
        except Exception:
            return None

    async def get_by_doi(self, doi: str) -> Optional[PaperSearchResult]:
        """One work by DOI (used for "Add by DOI"). None if OpenAlex doesn't know it."""
        try:
            work = await fetch(self.name, f"{OPENALEX_API_URL}/https://doi.org/{doi}",
                               params=self._base_params(), rate_per_sec=settings.OPENALEX_RATE_LIMIT)
        except Exception as e:
            logger.info(f"OpenAlex has no work for DOI {doi}: {e}")
            return None
        return self._parse_openalex_work(work) if work else None

    async def get_paper_details(self, openalex_id: str) -> Optional[dict]:
        try:
            return await fetch(self.name, f"{OPENALEX_API_URL}/{openalex_id}",
                               params=self._base_params(),
                               rate_per_sec=settings.OPENALEX_RATE_LIMIT)
        except Exception as e:
            logger.error(f"Error fetching OpenAlex work {openalex_id}: {e}")
            return None
