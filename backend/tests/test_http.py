"""Retry, caching and failure handling of the shared HTTP helper."""
import asyncio

import httpx
import pytest
import respx

from app.services import http_utils
from app.services.http_utils import SourceUnavailable, _cache_key, fetch

URL = "https://api.example.org/search"


@pytest.fixture(autouse=True)
def fast(monkeypatch, db):
    monkeypatch.setattr(http_utils, "wait_exponential", lambda **kw: (lambda rs: 0))
    http_utils._last_call.clear()


@respx.mock
def test_retries_on_429_then_succeeds_and_caches():
    route = respx.get(URL).mock(side_effect=[httpx.Response(429), httpx.Response(200, json={"ok": 1})])
    assert asyncio.run(fetch("t", URL, params={"q": "x"}, rate_per_sec=100)) == {"ok": 1}
    assert route.call_count == 2
    # second call is served from the cache
    assert asyncio.run(fetch("t", URL, params={"q": "x"}, rate_per_sec=100)) == {"ok": 1}
    assert route.call_count == 2


@respx.mock
def test_gives_up_with_source_unavailable():
    respx.get(URL).mock(return_value=httpx.Response(503))
    with pytest.raises(SourceUnavailable):
        asyncio.run(fetch("t", URL, params={"q": "y"}, rate_per_sec=100, attempts=2))


@respx.mock
def test_client_errors_are_not_retried():
    route = respx.get(URL).mock(return_value=httpx.Response(400))
    with pytest.raises(SourceUnavailable):
        asyncio.run(fetch("t", URL, params={"q": "z"}, rate_per_sec=100))
    assert route.call_count == 1


def test_api_keys_not_in_cache_key():
    assert _cache_key("s", URL, {"q": "a", "api_key": "secret1"}) == \
        _cache_key("s", URL, {"q": "a", "api_key": "secret2"})


@respx.mock
def test_pacing_works_across_event_loops():
    """Regression: the UI runs each action in a new event loop; concurrent requests must not crash."""
    respx.get(URL).mock(return_value=httpx.Response(200, json={"ok": 1}))

    async def burst(tag):
        return await asyncio.gather(*[fetch("loop-test", URL, params={"q": f"{tag}{i}"}, rate_per_sec=20,
                                            use_cache=False) for i in range(4)])
    assert len(asyncio.run(burst("a"))) == 4
    assert len(asyncio.run(burst("b"))) == 4  # second loop, same source
