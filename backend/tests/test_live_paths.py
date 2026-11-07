"""
Real code paths (no offline fakes): the actual OpenAI / Anthropic SDKs and the
real source clients, with HTTP mocked by respx using API-shaped responses.
Checks request formats, optional-key behaviour and graceful source failure.
"""
import asyncio
import json

import httpx
import pytest
import respx

from app.config import settings
from app.services import http_utils
from app.services.discovery_service import discover_papers


def _anthropic_reply(text):
    return httpx.Response(200, json={
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-x",
        "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
        "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}})


def _embeddings(request):
    body = json.loads(request.content)
    inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
    data = [{"object": "embedding", "index": i,
             "embedding": [((hash(t) >> k) & 1) - 0.5 for k in range(16)]} for i, t in enumerate(inputs)]
    return httpx.Response(200, json={"object": "list", "data": data, "model": "text-embedding-3-small",
                                     "usage": {"prompt_tokens": 1, "total_tokens": 1}})


OPENALEX = {"results": [{
    "id": f"https://openalex.org/W{i}", "title": f"Sepsis prediction study {i}",
    "abstract_inverted_index": {"Machine": [0], "learning": [1], "predicts": [2], "sepsis": [3]},
    "authorships": [{"author": {"display_name": "Ana Silva"}}], "publication_date": "2022-01-01",
    "doi": f"https://doi.org/10.1/oa{i}", "primary_location": {"source": {"display_name": "JAMA"}},
    "cited_by_count": i} for i in range(5)]}
S2 = {"data": [{"paperId": f"s2-{i}", "title": f"Sepsis prediction study {i}" if i < 2 else f"Early warning {i}",
                "abstract": "Early warning scores.", "authors": [{"name": "Li Wei"}], "year": 2021,
                "venue": "Nature Medicine", "externalIds": {"DOI": f"10.1/oa{i}" if i < 2 else f"10.2/s2{i}"},
                "citationCount": 10} for i in range(4)]}
S2_RECS = {"recommendedPapers": [{"paperId": "rec-1", "title": "Recommended sepsis paper",
                                  "abstract": "Related.", "authors": [], "year": 2023}]}


@pytest.fixture()
def live(monkeypatch, db):
    monkeypatch.setattr(settings, "OFFLINE_DEMO", False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(http_utils, "wait_exponential", lambda **kw: (lambda rs: 0))
    monkeypatch.setattr(settings, "SEMANTIC_SCHOLAR_RATE_LIMIT", 100.0)
    http_utils._last_call.clear()


def _routes(pubmed_status=200):
    respx.post("https://api.anthropic.com/v1/messages").mock(return_value=_anthropic_reply(
        '{"domain": "biomedical", "queries": ["sepsis machine learning"]}'))
    respx.post("https://api.openai.com/v1/embeddings").mock(side_effect=_embeddings)
    oa = respx.get("https://api.openalex.org/works").mock(return_value=httpx.Response(200, json=OPENALEX))
    s2 = respx.get("https://api.semanticscholar.org/graph/v1/paper/search").mock(
        return_value=httpx.Response(200, json=S2))
    recs = respx.get(url__regex=r"https://api\.semanticscholar\.org/recommendations/.*").mock(
        return_value=httpx.Response(200, json=S2_RECS))
    respx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").mock(
        return_value=httpx.Response(pubmed_status, text="<eSearchResult><IdList></IdList></eSearchResult>"))
    respx.get("https://api.crossref.org/works").mock(return_value=httpx.Response(200, json={"message": {"items": []}}))
    return oa, s2, recs


@respx.mock
def test_limited_mode_without_keys(live, monkeypatch, make_user, make_session):
    monkeypatch.setattr(settings, "OPENALEX_API_KEY", "")
    monkeypatch.setattr(settings, "SEMANTIC_SCHOLAR_API_KEY", "")
    oa, s2, recs = _routes(pubmed_status=503)  # PubMed down: must not break discovery
    u = make_user()
    s = make_session(u, "Machine learning for sepsis prediction")
    stats = asyncio.run(discover_papers(db=_db(s), session_id=s.id, user_id=u.id, topic=s.topic))
    assert stats["added"] == 7  # 5 OpenAlex + 4 S2 - 2 duplicates by DOI
    assert stats["sources"]["pubmed"]["errors"] == 1
    assert stats["sources"]["openalex"]["mode"] == "limited"
    req = oa.calls[0].request
    assert "api_key" not in str(req.url) and "per-page=20" in str(req.url)
    assert "x-api-key" not in s2.calls[0].request.headers
    assert recs.call_count == 0  # recommendations need a key


@respx.mock
def test_full_mode_with_keys(live, monkeypatch, make_user, make_session):
    monkeypatch.setattr(settings, "OPENALEX_API_KEY", "oa-key")
    monkeypatch.setattr(settings, "SEMANTIC_SCHOLAR_API_KEY", "s2-key")
    oa, s2, recs = _routes()
    u = make_user()
    s = make_session(u, "Machine learning for sepsis prediction")
    stats = asyncio.run(discover_papers(db=_db(s), session_id=s.id, user_id=u.id, topic=s.topic))
    assert stats["sources"]["openalex"]["mode"] == "full"
    assert "api_key=oa-key" in str(oa.calls[0].request.url) and "per-page=50" in str(oa.calls[0].request.url)
    assert s2.calls[0].request.headers["x-api-key"] == "s2-key"
    assert recs.call_count >= 1 and stats["added"] == 8  # + 1 recommended paper


def _db(s):
    from sqlalchemy.orm import object_session
    return object_session(s)
