"""
PubMed API integration service
Uses NCBI E-utilities API for searching and fetching papers
"""
import httpx
import logging
from typing import List, Optional
from datetime import datetime
from xml.etree import ElementTree as ET

from app.config import settings
from app.schemas.paper import PaperSearchResult
from app.models.paper import PaperSource

logger = logging.getLogger(__name__)

PUBMED_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_FETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
PUBMED_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


class PubMedService:
    """Service for interacting with PubMed API"""

    def __init__(self):
        self.api_key = settings.PUBMED_API_KEY
        self.timeout = 30.0

    async def search_papers(
        self,
        query: str,
        max_results: int = 20,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None
    ) -> List[PaperSearchResult]:
        """
        Search PubMed for papers matching the query

        Args:
            query: Search query
            max_results: Maximum number of results to return
            start_year: Filter by start year
            end_year: Filter by end year

        Returns:
            List of paper search results
        """
        try:
            # Build search term with date filters
            search_term = query
            if start_year or end_year:
                start = start_year or 1900
                end = end_year or datetime.now().year
                search_term += f" AND {start}:{end}[dp]"

            # Search for PMIDs
            pmids = await self._search_pmids(search_term, max_results)
            if not pmids:
                logger.info(f"No results found for query: {query}")
                return []

            # Fetch paper details
            papers = await self._fetch_paper_details(pmids)
            return papers

        except Exception as e:
            logger.error(f"Error searching PubMed: {e}")
            return []

    async def _search_pmids(self, query: str, max_results: int) -> List[str]:
        """
        Search PubMed and return list of PMIDs

        Args:
            query: Search query
            max_results: Maximum number of results

        Returns:
            List of PubMed IDs
        """
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "xml",
            "sort": "relevance"
        }

        if self.api_key:
            params["api_key"] = self.api_key

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(PUBMED_SEARCH_URL, params=params)
            response.raise_for_status()

            # Parse XML response
            root = ET.fromstring(response.content)
            pmids = [id_elem.text for id_elem in root.findall(".//Id")]

            logger.info(f"Found {len(pmids)} PMIDs for query: {query}")
            return pmids

    async def _fetch_paper_details(self, pmids: List[str]) -> List[PaperSearchResult]:
        """
        Fetch detailed information for list of PMIDs

        Args:
            pmids: List of PubMed IDs

        Returns:
            List of paper search results
        """
        if not pmids:
            return []

        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "rettype": "abstract"
        }

        if self.api_key:
            params["api_key"] = self.api_key

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(PUBMED_FETCH_URL, params=params)
            response.raise_for_status()

            # Parse XML response
            root = ET.fromstring(response.content)
            papers = []

            for article in root.findall(".//PubmedArticle"):
                try:
                    paper = self._parse_pubmed_article(article)
                    if paper:
                        papers.append(paper)
                except Exception as e:
                    logger.warning(f"Error parsing article: {e}")
                    continue

            logger.info(f"Successfully parsed {len(papers)} papers")
            return papers

    def _parse_pubmed_article(self, article_elem: ET.Element) -> Optional[PaperSearchResult]:
        """
        Parse PubMed article XML element into PaperSearchResult

        Args:
            article_elem: XML element containing article data

        Returns:
            PaperSearchResult or None if parsing fails
        """
        try:
            # Get PMID
            pmid_elem = article_elem.find(".//PMID")
            if pmid_elem is None:
                return None
            pmid = pmid_elem.text

            # Get article metadata
            article_meta = article_elem.find(".//Article")
            if article_meta is None:
                return None

            # Title
            title_elem = article_meta.find(".//ArticleTitle")
            title = title_elem.text if title_elem is not None else "No title"

            # Abstract
            abstract_parts = []
            for abstract_text in article_meta.findall(".//AbstractText"):
                label = abstract_text.get("Label", "")
                text = abstract_text.text or ""
                if label:
                    abstract_parts.append(f"{label}: {text}")
                else:
                    abstract_parts.append(text)
            abstract = " ".join(abstract_parts) if abstract_parts else None

            # Authors
            authors = []
            author_list = article_meta.find(".//AuthorList")
            if author_list is not None:
                for author in author_list.findall(".//Author"):
                    last_name = author.find("LastName")
                    fore_name = author.find("ForeName")
                    if last_name is not None:
                        name = last_name.text
                        if fore_name is not None:
                            name = f"{fore_name.text} {name}"
                        authors.append(name)

            # Journal
            journal_elem = article_meta.find(".//Journal/Title")
            journal = journal_elem.text if journal_elem is not None else None

            # Publication date
            pub_date_elem = article_meta.find(".//PubDate")
            pub_date_str = None
            if pub_date_elem is not None:
                year = pub_date_elem.find("Year")
                month = pub_date_elem.find("Month")
                day = pub_date_elem.find("Day")

                if year is not None:
                    pub_date_str = year.text
                    if month is not None:
                        pub_date_str = f"{year.text}-{month.text}"
                        if day is not None:
                            pub_date_str = f"{year.text}-{month.text}-{day.text}"

            # DOI
            doi = None
            article_id_list = article_elem.find(".//PubmedData/ArticleIdList")
            if article_id_list is not None:
                for article_id in article_id_list.findall(".//ArticleId"):
                    if article_id.get("IdType") == "doi":
                        doi = article_id.text
                        break

            return PaperSearchResult(
                title=title,
                abstract=abstract,
                authors=authors if authors else None,
                publication_date=pub_date_str,
                journal=journal,
                doi=doi,
                source=PaperSource.PUBMED,
                source_id=pmid,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            )

        except Exception as e:
            logger.error(f"Error parsing PubMed article: {e}")
            return None

    async def fetch_full_text(self, pmid: str) -> Optional[str]:
        """
        Attempt to fetch full text for a PubMed article
        Note: Full text availability is limited in PubMed Central

        Args:
            pmid: PubMed ID

        Returns:
            Full text if available, None otherwise
        """
        # This is a placeholder - full text retrieval from PMC requires additional logic
        # and may not be available for all papers
        logger.info(f"Full text retrieval for PMID {pmid} not yet implemented")
        return None
