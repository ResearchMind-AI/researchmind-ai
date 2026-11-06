"""
arXiv API (free, no key). Preprints for AI/ML, CS, physics and maths.
arXiv asks for no more than one request every 3 seconds.
"""
import logging
import re
from typing import List, Optional
from xml.etree import ElementTree as ET

from app.models.paper import PaperSource
from app.schemas.paper import PaperSearchResult
from app.services.http_utils import fetch

logger = logging.getLogger(__name__)

ARXIV_URL = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


class ArxivService:
    name = "arxiv"
    label = "arXiv"
    mode = "full"  # no key needed
    default_max_results = 20

    async def search(self, query: str, max_results: Optional[int] = None,
                     start_year: Optional[int] = None, end_year: Optional[int] = None
                     ) -> List[PaperSearchResult]:
        terms = " AND ".join(f"all:{w}" for w in re.findall(r"[\w-]+", query)[:8]) or f"all:{query}"
        params = {"search_query": terms, "start": 0,
                  "max_results": min(max_results or self.default_max_results, 50),
                  "sortBy": "relevance", "sortOrder": "descending"}
        xml = await fetch(self.name, ARXIV_URL, params=params, rate_per_sec=1 / 3, as_json=False)
        papers = self.parse_feed(xml)
        if start_year or end_year:
            papers = [p for p in papers if p.publication_date and
                      (start_year or 0) <= int(p.publication_date[:4]) <= (end_year or 9999)]
        logger.info(f"arXiv: {len(papers)} papers for '{query}'")
        return papers

    async def get_by_id(self, arxiv_id: str) -> Optional[PaperSearchResult]:
        try:
            xml = await fetch(self.name, ARXIV_URL, params={"id_list": arxiv_id},
                              rate_per_sec=1 / 3, as_json=False)
            papers = self.parse_feed(xml)
            return papers[0] if papers else None
        except Exception as e:
            logger.error(f"arXiv lookup failed for {arxiv_id}: {e}")
            return None

    @staticmethod
    def parse_feed(xml: str) -> List[PaperSearchResult]:
        root = ET.fromstring(xml)
        out = []
        for entry in root.findall("a:entry", NS):
            title = " ".join((entry.findtext("a:title", "", NS) or "").split())
            raw_id = entry.findtext("a:id", "", NS) or ""
            if not title or "arxiv.org/abs/" not in raw_id:
                continue
            arxiv_id = raw_id.split("arxiv.org/abs/")[-1]
            out.append(PaperSearchResult(
                title=title,
                abstract=" ".join((entry.findtext("a:summary", "", NS) or "").split()) or None,
                authors=[a.findtext("a:name", "", NS) for a in entry.findall("a:author", NS)] or None,
                publication_date=(entry.findtext("a:published", "", NS) or "")[:10] or None,
                journal="arXiv",
                doi=entry.findtext("arxiv:doi", None, NS),
                source=PaperSource.ARXIV,
                source_id=arxiv_id,
                url=f"https://arxiv.org/abs/{arxiv_id}",
                citations_count=0,
            ))
        return out
