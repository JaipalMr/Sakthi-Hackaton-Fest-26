"""Backend-only LLM provider adapters. API keys are read from the environment and never leave the server.

Providers share one internal format (Anthropic-style content blocks) so the assistant loop is provider-agnostic:
  * anthropic  - Claude via the Anthropic SDK
  * openai     - any OpenAI-compatible chat-completions endpoint (OpenAI, Groq, Together, Ollama, LM Studio, ...)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolUse:
    id: str
    name: str
    input: dict


@dataclass
class LLMTurn:
    text: str
    tool_uses: list[ToolUse] = field(default_factory=list)
    raw_content: list[dict] = field(default_factory=list)  # provider-neutral blocks to echo back


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMTurn: ...


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout: float):
        import anthropic  # imported lazily so the package is optional in demo mode
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=1)
        self.model = model

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMTurn:
        kw = dict(model=self.model, max_tokens=1200, system=system, messages=messages)
        if tools:
            kw["tools"] = tools
        resp = self._client.messages.create(**kw)
        text, uses, raw = [], [], []
        for b in resp.content:
            if b.type == "text":
                text.append(b.text)
                raw.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                uses.append(ToolUse(b.id, b.name, dict(b.input)))
                raw.append({"type": "tool_use", "id": b.id, "name": b.name, "input": dict(b.input)})
        return LLMTurn("".join(text), uses, raw)


def _to_openai_messages(system: str, messages: list[dict]) -> list[dict]:
    """Translate neutral/Anthropic-style messages (text, tool_use, tool_result blocks) to OpenAI chat format."""
    out: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        c = m["content"]
        if isinstance(c, str):
            out.append({"role": m["role"], "content": c})
            continue
        if m["role"] == "assistant":
            text = "".join(b.get("text", "") for b in c if b.get("type") == "text")
            calls = [{"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b["input"])}}
                     for b in c if b.get("type") == "tool_use"]
            msg: dict = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        else:  # user turn carrying tool_result blocks
            for b in c:
                if b.get("type") == "tool_result":
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": str(b["content"])})
                elif b.get("type") == "text":
                    out.append({"role": "user", "content": b["text"]})
    return out


class OpenAICompatProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str, timeout: float, base_url: str | None = None):
        import httpx
        self._http = httpx.Client(timeout=timeout)
        self._key = api_key
        self._url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
        self.model = model

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMTurn:
        body: dict = {"model": self.model, "max_tokens": 1200, "messages": _to_openai_messages(system, messages)}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                                "parameters": t["input_schema"]}} for t in tools]
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        r = self._http.post(self._url, json=body, headers=headers)
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        text = msg.get("content") or ""
        uses, raw = [], ([{"type": "text", "text": text}] if text else [])
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"__malformed__": tc["function"].get("arguments")}  # fails validation downstream, reported to the model
            uses.append(ToolUse(tc["id"], tc["function"]["name"], args))
            raw.append({"type": "tool_use", "id": tc["id"], "name": tc["function"]["name"], "input": args})
        return LLMTurn(text, uses, raw)


def build_provider(settings) -> LLMProvider | None:
    if not settings.llm_live:
        return None
    if settings.llm_provider == "openai":
        return OpenAICompatProvider(settings.openai_api_key, settings.llm_model, settings.llm_timeout, settings.openai_base_url or None)
    return AnthropicProvider(settings.anthropic_api_key, settings.llm_model, settings.llm_timeout)
