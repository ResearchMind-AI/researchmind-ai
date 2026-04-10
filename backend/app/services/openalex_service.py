"""
OpenAlex API integration service
Uses OpenAlex API for searching academic papers
"""
import httpx
import logging
from typing import List, Optional
from datetime import datetime

from app.schemas.paper import PaperSearchResult
from app.models.paper import PaperSource

logger = logging.getLogger(__name__)

OPENALEX_API_URL = "https://api.openalex.org/works"


class OpenAlexService:
    """Service for interacting with OpenAlex API"""

    def __init__(self):
        self.timeout = 30.0
        # OpenAlex recommends including email in User-Agent
        self.headers = {
            "User-Agent": "ResearchMindAI (mailto:support@researchmind.ai)"
        }

    async def search_papers(
        self,
        query: str,
        max_results: int = 20,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None
    ) -> List[PaperSearchResult]:
        """
        Search OpenAlex for papers matching the query

        Args:
            query: Search query
            max_results: Maximum number of results to return
            start_year: Filter by start year
            end_year: Filter by end year

        Returns:
            List of paper search results
        """
        try:
            # Build filter string
            filters = []

            # Add date filters
            if start_year:
                filters.append(f"from_publication_date:{start_year}-01-01")
            if end_year:
                filters.append(f"to_publication_date:{end_year}-12-31")

            # Build params
            params = {
                "search": query,
                "per-page": min(max_results, 100),  # OpenAlex max is 100
                "sort": "relevance_score:desc",
                "select": "id,title,abstract_inverted_index,authorships,publication_date,primary_location,doi,cited_by_count"
            }

            if filters:
                params["filter"] = ",".join(filters)

            async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
                response = await client.get(OPENALEX_API_URL, params=params)
                response.raise_for_status()

                data = response.json()
                results = data.get("results", [])

                papers = []
                for work in results:
                    paper = self._parse_openalex_work(work)
                    if paper:
                        papers.append(paper)

                logger.info(f"Found {len(papers)} papers from OpenAlex for query: {query}")
                return papers

        except Exception as e:
            logger.error(f"Error searching OpenAlex: {e}")
            return []

    def _parse_openalex_work(self, work: dict) -> Optional[PaperSearchResult]:
        """
        Parse OpenAlex work JSON into PaperSearchResult

        Args:
            work: OpenAlex work dictionary

        Returns:
            PaperSearchResult or None if parsing fails
        """
        try:
            # Extract OpenAlex ID
            openalex_id = work.get("id", "").replace("https://openalex.org/", "")
            if not openalex_id:
                return None

            # Title
            title = work.get("title") or "No title"

            # Abstract - reconstruct from inverted index
            abstract = self._reconstruct_abstract(work.get("abstract_inverted_index"))

            # Authors
            authors = []
            authorships = work.get("authorships", [])
            for authorship in authorships:
                author = authorship.get("author", {})
                display_name = author.get("display_name")
                if display_name:
                    authors.append(display_name)

            # Journal
            journal = None
            primary_location = work.get("primary_location")
            if primary_location:
                source = primary_location.get("source", {})
                journal = source.get("display_name")

            # Publication date
            pub_date = work.get("publication_date")

            # DOI
            doi = work.get("doi")
            if doi:
                doi = doi.replace("https://doi.org/", "")

            # Citations count
            citations_count = work.get("cited_by_count", 0)

            # URL
            url = work.get("id")  # OpenAlex ID is a URL

            return PaperSearchResult(
                title=title,
                abstract=abstract,
                authors=authors if authors else None,
                publication_date=pub_date,
                journal=journal,
                doi=doi,
                source=PaperSource.OPENALEX,
                source_id=openalex_id,
                url=url,
                citations_count=citations_count
            )

        except Exception as e:
            logger.error(f"Error parsing OpenAlex work: {e}")
            return None

    def _reconstruct_abstract(self, inverted_index: Optional[dict]) -> Optional[str]:
        """
        Reconstruct abstract text from OpenAlex inverted index

        Args:
            inverted_index: Dictionary mapping words to positions

        Returns:
            Reconstructed abstract text or None
        """
        if not inverted_index:
            return None

        try:
            # Create list to hold words at each position
            max_position = max(
                max(positions) for positions in inverted_index.values()
            )
            words = [""] * (max_position + 1)

            # Fill in words at their positions
            for word, positions in inverted_index.items():
                for pos in positions:
                    words[pos] = word

            # Join words to form abstract
            abstract = " ".join(words).strip()
            return abstract if abstract else None

        except Exception as e:
            logger.error(f"Error reconstructing abstract: {e}")
            return None

    async def get_paper_details(self, openalex_id: str) -> Optional[dict]:
        """
        Get detailed information for a specific OpenAlex work

        Args:
            openalex_id: OpenAlex work ID (e.g., W2741809807)

        Returns:
            Work details dictionary or None
        """
        try:
            url = f"https://api.openalex.org/works/{openalex_id}"

            async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
                response = await client.get(url)
                response.raise_for_status()

                return response.json()

        except Exception as e:
            logger.error(f"Error fetching OpenAlex work {openalex_id}: {e}")
            return None
