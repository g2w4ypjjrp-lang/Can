"""Claude API istemcisi. Tüm model çağrıları buradan geçer; maliyet ve token kullanımı ölçülür."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

import anthropic

log = logging.getLogger("bizcenter.llm")

# USD / 1M token (girdi, çıktı). Kaynak: Anthropic fiyat listesi; değişirse burada güncellenir.
PRICING: dict[str, tuple[Decimal, Decimal]] = {
    "claude-opus-5-5": (Decimal("4"), Decimal("20")),
    "claude-sonnet-5-5": (Decimal("2"), Decimal("10")),
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
    "claude-fable-5-2": (Decimal("8"), Decimal("40")),
}
WEB_SEARCH_USD_PER_REQUEST = Decimal("0.01")


class LLMError(Exception):
    """Kullanıcıya gösterilebilir, iç ayrıntı içermeyen model hatası."""


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    web_searches: int = 0
    cost_usd: Decimal = Decimal(0)
    data: Any = None
    sources: list[dict[str, str]] = field(default_factory=list)


class LLM(Protocol):
    async def complete(self, *, system: str, user: str, schema: dict[str, Any] | None = None,
                       web_search: bool = False, effort: str = "medium",
                       max_tokens: int = 16000) -> LLMResult: ...


def estimate_cost(model: str, input_tokens: int, output_tokens: int, web_searches: int = 0) -> Decimal:
    inp, out = PRICING.get(model, PRICING["claude-opus-5-5"])
    return ((inp * input_tokens + out * output_tokens) / Decimal(1_000_000)
            + WEB_SEARCH_USD_PER_REQUEST * web_searches).quantize(Decimal("0.000001"))


class ClaudeLLM:
    def __init__(self, api_key: str, model: str, max_web_searches: int = 5) -> None:
        if not api_key:
            raise LLMError("Anthropic API anahtarı yapılandırılmadı (BC_ANTHROPIC_API_KEY)")
        self.client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=3, timeout=600.0)
        self.model = model
        self.max_web_searches = max_web_searches

    async def complete(self, *, system: str, user: str, schema: dict[str, Any] | None = None,
                       web_search: bool = False, effort: str = "medium",
                       max_tokens: int = 16000) -> LLMResult:
        output_config: dict[str, Any] = {"effort": effort}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        tools: list[dict[str, Any]] = []
        if web_search:
            tools.append({"type": "web_search_20260209", "name": "web_search",
                          "max_uses": self.max_web_searches})
        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
        result = LLMResult(text="", model=self.model)

        # pause_turn: sunucu araç döngüsü duraklarsa aynı konuşmayla devam edilir (en fazla 5 kez).
        for _ in range(5):
            try:
                resp = await self.client.beta.messages.create(
                    model=self.model, max_tokens=max_tokens, system=system, messages=messages,
                    output_config=output_config, betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default", **({"tools": tools} if tools else {}),
                )
            except anthropic.AuthenticationError as exc:
                raise LLMError("Anthropic API anahtarı geçersiz") from exc
            except anthropic.PermissionDeniedError as exc:
                raise LLMError("Anthropic API anahtarının bu modele erişimi yok") from exc
            except anthropic.BadRequestError as exc:
                log.error("claude bad request: %s", exc.message)
                raise LLMError("Model isteği reddedildi (geçersiz istek)") from exc
            except anthropic.RateLimitError as exc:
                raise LLMError("Anthropic hız sınırına takıldı; daha sonra tekrar deneyin") from exc
            except anthropic.APIStatusError as exc:
                raise LLMError(f"Anthropic hizmet hatası ({exc.status_code})") from exc
            except anthropic.APIConnectionError as exc:
                raise LLMError("Anthropic API'ye bağlanılamadı") from exc

            u = resp.usage
            result.model = resp.model
            result.input_tokens += (u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0) \
                + (getattr(u, "cache_creation_input_tokens", 0) or 0)
            result.output_tokens += u.output_tokens or 0
            stu = getattr(u, "server_tool_use", None)
            result.web_searches += (getattr(stu, "web_search_requests", 0) or 0) if stu else 0

            last_text = ""
            for block in resp.content:
                if block.type == "text":
                    result.text += block.text
                    last_text += block.text
                    for c in getattr(block, "citations", None) or []:
                        url = getattr(c, "url", None)
                        if url and all(s["url"] != url for s in result.sources):
                            result.sources.append({"url": url, "title": getattr(c, "title", "") or ""})

            if resp.stop_reason == "pause_turn":
                messages = [*messages[:1], {"role": "assistant", "content": resp.content}]
                continue
            if resp.stop_reason == "refusal":
                raise LLMError("Model bu isteği güvenlik nedeniyle reddetti")
            if resp.stop_reason == "max_tokens":
                raise LLMError("Model yanıtı uzunluk sınırında kesildi")
            break
        else:
            raise LLMError("Model yanıtı tamamlanamadı")
        if schema is not None:
            result.text = last_text  # yapılandırılmış çıktı yalnızca son yanıtta

        result.cost_usd = estimate_cost(result.model, result.input_tokens, result.output_tokens,
                                        result.web_searches)
        if schema is not None:
            try:
                result.data = json.loads(result.text)
            except json.JSONDecodeError as exc:
                raise LLMError("Model geçerli bir plan döndürmedi") from exc
        return result
