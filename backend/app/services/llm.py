"""
LLM client wrapper.

Uses Claude (Anthropic) when ANTHROPIC_API_KEY is set, otherwise OpenAI's
CHAT_MODEL. Offers plain completion, JSON completion and streaming.
"""
import json
import logging
import re
from typing import Any, AsyncIterator, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)


def extract_json(text: str) -> Any:
    """Parse JSON from an LLM reply, tolerating code fences and surrounding prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
        if start == -1:
            raise
        end = max(text.rfind("}"), text.rfind("]"))
        return json.loads(text[start:end + 1])


class LLMClient:
    """Thin provider-agnostic chat client."""

    def __init__(self):
        self.provider = settings.llm_provider
        if settings.OFFLINE_DEMO:
            self.provider = "offline"
        if self.provider == "anthropic":
            from anthropic import AsyncAnthropic
            self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            self.model = settings.CLAUDE_MODEL
        elif self.provider == "openai":
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            self.model = settings.CHAT_MODEL
        else:
            from app.services.offline import FakeLLM
            self._client = FakeLLM()
            self.model = "offline-fake"

    async def complete(
        self,
        prompt: str,
        system: str = "You are a careful research assistant.",
        max_tokens: int = 2000,
        temperature: float = 0.3,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        messages = list(history or []) + [{"role": "user", "content": prompt}]
        if self.provider == "anthropic":
            resp = await self._client.messages.create(
                model=self.model, system=system, messages=messages,
                max_tokens=max_tokens, temperature=temperature,
            )
            return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        if self.provider == "openai":
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}] + messages,
                max_tokens=max_tokens, temperature=temperature,
            )
            return resp.choices[0].message.content or ""
        return await self._client.complete(prompt, system=system)

    async def complete_json(self, prompt: str, system: str = "You are a careful research assistant. "
                            "Respond with valid JSON only.", max_tokens: int = 3000) -> Any:
        text = await self.complete(prompt, system=system, max_tokens=max_tokens, temperature=0.2)
        try:
            return extract_json(text)
        except Exception:
            logger.warning("LLM returned invalid JSON, retrying once")
            text = await self.complete(
                prompt + "\n\nYour previous reply was not valid JSON. Return ONLY the JSON.",
                system=system, max_tokens=max_tokens, temperature=0.0,
            )
            return extract_json(text)

    async def stream(
        self,
        prompt: str,
        system: str = "You are a careful research assistant.",
        max_tokens: int = 1500,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncIterator[str]:
        messages = list(history or []) + [{"role": "user", "content": prompt}]
        if self.provider == "anthropic":
            async with self._client.messages.stream(
                model=self.model, system=system, messages=messages,
                max_tokens=max_tokens, temperature=0.2,
            ) as s:
                async for text in s.text_stream:
                    yield text
        elif self.provider == "openai":
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}] + messages,
                max_tokens=max_tokens, temperature=0.2, stream=True,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        else:
            text = await self._client.complete(prompt, system=system)
            for word in text.split(" "):
                yield word + " "
