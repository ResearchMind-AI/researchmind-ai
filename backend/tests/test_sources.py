"""Parsers for each paper source, using payloads shaped like the real APIs."""
from app.models.paper import PaperSource
from app.services.arxiv_service import ArxivService
from app.services.openalex_service import OpenAlexService
from app.services.pubmed_service import PubMedService
from app.services.semantic_scholar_service import SemanticScholarService


def test_openalex_parse_rebuilds_abstract():
    work = {
        "id": "https://openalex.org/W123", "title": "Grounded answers",
        "abstract_inverted_index": {"Large": [0], "models": [1], "hallucinate": [2]},
        "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
        "publication_date": "2023-05-01", "doi": "https://doi.org/10.1/abc",
        "primary_location": {"source": {"display_name": "Nature"}}, "cited_by_count": 7,
    }
    p = OpenAlexService()._parse_openalex_work(work)
    assert p.abstract == "Large models hallucinate"
    assert p.doi == "10.1/abc" and p.source_id == "W123" and p.journal == "Nature"
    assert p.url == "https://doi.org/10.1/abc"


def test_semantic_scholar_parse():
    item = {"paperId": "abc123", "title": "RAG survey", "abstract": "A survey.",
            "authors": [{"name": "Jane Doe"}], "year": 2024, "venue": "ACL",
            "externalIds": {"DOI": "10.2/xyz"}, "citationCount": 12, "url": "https://s2/abc123"}
    p = SemanticScholarService._parse(item)
    assert p.source == PaperSource.SEMANTIC_SCHOLAR and p.doi == "10.2/xyz"
    assert p.publication_date == "2024" and p.authors == ["Jane Doe"]
    assert SemanticScholarService._parse({"paperId": "x"}) is None  # no title


ARXIV_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.01234v2</id>
    <published>2024-01-03T00:00:00Z</published>
    <title>Retrieval   Augmented
      Generation</title>
    <summary>We study RAG.</summary>
    <author><name>Alan Turing</name></author>
    <arxiv:doi>10.3/arx</arxiv:doi>
  </entry>
</feed>"""


def test_arxiv_parse():
    [p] = ArxivService.parse_feed(ARXIV_FEED)
    assert p.title == "Retrieval Augmented Generation"
    assert p.source_id == "2401.01234v2" and p.publication_date == "2024-01-03"
    assert p.doi == "10.3/arx" and p.url == "https://arxiv.org/abs/2401.01234v2"


PUBMED_XML = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>999</PMID>
<Article><Journal><Title>The Lancet</Title><JournalIssue><PubDate><Year>2021</Year><Month>Mar</Month>
<Day>5</Day></PubDate></JournalIssue></Journal>
<ArticleTitle>AI in <i>sepsis</i> detection</ArticleTitle>
<Abstract><AbstractText Label="BACKGROUND">Sepsis is <b>deadly</b>.</AbstractText></Abstract>
<AuthorList><Author><LastName>Smith</LastName><ForeName>John</ForeName></Author></AuthorList>
</Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.4/pm</ArticleId>
</ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""


def test_pubmed_parse_handles_inline_tags_and_month_names():
    [p] = PubMedService().parse_articles(PUBMED_XML)
    assert p.title == "AI in sepsis detection"
    assert p.abstract == "BACKGROUND: Sepsis is deadly."
    assert p.publication_date == "2021-03-05"
    assert p.doi == "10.4/pm" and p.authors == ["John Smith"]


def test_modes_switch_with_keys(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "OPENALEX_API_KEY", "")
    monkeypatch.setattr(settings, "SEMANTIC_SCHOLAR_API_KEY", "")
    oa, s2 = OpenAlexService(), SemanticScholarService()
    assert (oa.mode, oa.default_max_results) == ("limited", 20)
    assert (s2.mode, s2._headers) == ("limited", {})
    monkeypatch.setattr(settings, "OPENALEX_API_KEY", "k1")
    monkeypatch.setattr(settings, "SEMANTIC_SCHOLAR_API_KEY", "k2")
    oa, s2 = OpenAlexService(), SemanticScholarService()
    assert (oa.mode, oa.default_max_results) == ("full", 50)
    assert oa._base_params()["api_key"] == "k1"
    assert s2.mode == "full" and s2._headers == {"x-api-key": "k2"}
