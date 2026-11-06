"""
Shared HTTP helper for paper-source APIs.

- Retries with exponential backoff on rate limits (429), server errors and
  timeouts, honouring Retry-After when the API sends it.
- Spaces requests per source so we stay inside free-tier rate limits.
- Caches successful responses in the database to save free quota.
"""
import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx
from tenacity import (
    AsyncRetrying, RetryError, retry_if_exception, stop_after_attempt, wait_exponential,
)

from app.config import settings

logger = logging.getLogger(__name__)

USER_AGENT = "ResearchMindAI/1.0 (research POC)"
SECRET_PARAMS = {"api_key", "apikey", "key"}

_last_call: Dict[str, float] = {}
_locks: Dict[tuple, asyncio.Lock] = {}


class SourceUnavailable(Exception):
    """Raised when a source keeps failing after retries."""


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


def _cache_key(source: str, url: str, params: Optional[dict]) -> str:
    clean = {k: v for k, v in (params or {}).items() if k.lower() not in SECRET_PARAMS}
    raw = json.dumps([source, url, clean], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_get(key: str) -> Optional[Any]:
    from app.core.database import SessionLocal
    from app.models.research import ApiCache
    db = SessionLocal()
    try:
        row = db.query(ApiCache).filter(ApiCache.cache_key == key).first()
        if not row:
            return None
        created = row.created_at
        if created is not None:
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - created > timedelta(hours=settings.CACHE_TTL_HOURS):
                return None
        return row.payload
    except Exception as e:  # cache problems must never break a search
        logger.debug(f"cache read failed: {e}")
        return None
    finally:
        db.close()


def _cache_put(key: str, source: str, payload: Any) -> None:
    from app.core.database import SessionLocal
    from app.models.research import ApiCache
    db = SessionLocal()
    try:
        row = db.query(ApiCache).filter(ApiCache.cache_key == key).first()
        if row:
            row.payload = payload
            row.created_at = datetime.now(timezone.utc)
        else:
            db.add(ApiCache(cache_key=key, source=source, payload=payload))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.debug(f"cache write failed: {e}")
    finally:
        db.close()


async def _pace(source: str, rate_per_sec: float) -> None:
    # asyncio locks are bound to one event loop; the UI starts a new loop per action.
    loop_key = (id(asyncio.get_running_loop()), source)
    if len(_locks) > 200:
        _locks.clear()
    lock = _locks.setdefault(loop_key, asyncio.Lock())
    async with lock:
        min_interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0
        wait = _last_call.get(source, 0) + min_interval - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call[source] = time.monotonic()


async def fetch(
    source: str,
    url: str,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    rate_per_sec: float = 1.0,
    as_json: bool = True,
    use_cache: bool = True,
    attempts: int = 4,
    timeout: float = 30.0,
) -> Any:
    """GET a URL with pacing, retries and caching. Returns parsed JSON or text."""
    key = _cache_key(source, url, params)
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            return cached if as_json else cached.get("text")

    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}

    async def _once():
        await _pace(source, rate_per_sec)
        async with httpx.AsyncClient(timeout=timeout, headers=hdrs, follow_redirects=True) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    await asyncio.sleep(min(int(retry_after), 20))
            resp.raise_for_status()
            return resp.json() if as_json else {"text": resp.text}

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(multiplier=1, min=1, max=16),
            retry=retry_if_exception(_retryable),
            reraise=True,
        ):
            with attempt:
                payload = await _once()
    except (RetryError, httpx.HTTPError) as e:
        raise SourceUnavailable(f"{source}: {e}") from e

    if use_cache:
        _cache_put(key, source, payload)
    return payload if as_json else payload["text"]
