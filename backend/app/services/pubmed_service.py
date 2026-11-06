"""
PubMed API integration service
Uses NCBI E-utilities API for searching and fetching papers
"""
import logging
from typing import List, Optional
from datetime import datetime
from xml.etree import ElementTree as ET

from app.config import settings
from app.schemas.paper import PaperSearchResult
from app.models.paper import PaperSource
from app.services.http_utils import fetch

logger = logging.getLogger(__name__)

PUBMED_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_FETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
PUBMED_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


class PubMedService:
    """Service for interacting with PubMed API (free; a key raises the rate limit)"""

    name = "pubmed"
    label = "PubMed"

    def __init__(self):
        self.api_key = settings.PUBMED_API_KEY
        self.timeout = 30.0

    @property
    def mode(self) -> str:
        return "full" if self.api_key else "limited"

    @property
    def default_max_results(self) -> int:
        return 30 if self.api_key else 20

    @property
    def _rate(self) -> float:
        return 9.0 if self.api_key else 2.5

    def _common(self) -> dict:
        params = {"tool": "ResearchMindAI"}
        if self.api_key:
            params["api_key"] = self.api_key
        if settings.PUBMED_EMAIL:
            params["email"] = settings.PUBMED_EMAIL
        return params

    async def search(self, query: str, max_results: Optional[int] = None,
                     start_year: Optional[int] = None, end_year: Optional[int] = None
                     ) -> List[PaperSearchResult]:
        """Search PubMed; raises SourceUnavailable if the API keeps failing."""
        term = query
        if start_year or end_year:
            term += f" AND {start_year or 1900}:{end_year or datetime.now().year}[dp]"
        pmids = await self._search_pmids(term, max_results or self.default_max_results)
        return await self._fetch_paper_details(pmids) if pmids else []

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
            return await self.search(query, max_results, start_year, end_year)

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
        params = {**self._common(), "db": "pubmed", "term": query, "retmax": max_results,
                  "retmode": "xml", "sort": "relevance"}
        xml = await fetch(self.name, PUBMED_SEARCH_URL, params=params,
                          rate_per_sec=self._rate, as_json=False)
        root = ET.fromstring(xml)
        pmids = [id_elem.text for id_elem in root.findall(".//IdList/Id")]
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

        params = {**self._common(), "db": "pubmed", "id": ",".join(pmids),
                  "retmode": "xml", "rettype": "abstract"}
        xml = await fetch(self.name, PUBMED_FETCH_URL, params=params,
                          rate_per_sec=self._rate, as_json=False)
        return self.parse_articles(xml)

    def parse_articles(self, xml: str) -> List[PaperSearchResult]:
        root = ET.fromstring(xml)
        papers = []
        for article in root.findall(".//PubmedArticle"):
            try:
                paper = self._parse_pubmed_article(article)
                if paper:
                    papers.append(paper)
            except Exception as e:
                logger.warning(f"Error parsing article: {e}")
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
            title = "".join(title_elem.itertext()).strip() if title_elem is not None else ""
            if not title:
                return None

            # Abstract
            abstract_parts = []
            for abstract_text in article_meta.findall(".//AbstractText"):
                label = abstract_text.get("Label", "")
                text = "".join(abstract_text.itertext()).strip()
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
                        m = month.text.strip()
                        m_num = int(m) if m.isdigit() else MONTHS.get(m[:3].lower())
                        if m_num:
                            pub_date_str = f"{year.text}-{m_num:02d}"
                            if day is not None and day.text.strip().isdigit():
                                pub_date_str += f"-{int(day.text):02d}"

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
