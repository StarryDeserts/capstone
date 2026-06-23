from __future__ import annotations

import json
from typing import Any

# Anthropic server-side web search tool. Confirm the current identifier against
# Anthropic docs (use context7) at implementation time; only the wrapper changes.
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}


def _extract_text(resp: Any) -> str:
    parts = []
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts)


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if "```" in t:
            t = t[: t.rfind("```")]
    return t.strip()


class LLM:
    def __init__(self, client: Any, model: str):
        self.client = client
        self.model = model

    async def generate_json(self, *, system: str, user: str,
                            web_search: bool = False, max_tokens: int = 4096) -> dict:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if web_search:
            kwargs["tools"] = [WEB_SEARCH_TOOL]
        resp = await self.client.messages.create(**kwargs)
        text = _strip_fences(_extract_text(resp))
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM did not return valid JSON: {text[:200]!r}") from exc
