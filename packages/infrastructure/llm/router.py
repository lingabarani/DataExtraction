"""
LLM router: picks the provider from LLM_PROVIDER, walks LLM_FALLBACK_CHAIN on failure
and enforces LLM_DAILY_TOKEN_BUDGET.

    from packages.infrastructure.llm import get_llm
    llm = get_llm()
    result = llm.chat([{"role": "user", "content": "..."}], schema=MyModel, purpose="planner")

Environment is read on every get_llm() call, so switching provider needs no restart.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel

from packages.infrastructure.llm.base import (
    LLMBudgetExceeded, LLMError, LLMProvider, LLMResult, LLMSchemaError, LLMUnavailable,
)
from packages.infrastructure.llm.usage import daily_budget, tokens_used_today

logger = logging.getLogger("dataextraction.llm.router")

KNOWN_PROVIDERS = ("groq", "bedrock", "ollama")


def _build(name: str) -> LLMProvider:
    if name == "groq":
        from packages.infrastructure.llm.groq_provider import GroqProvider
        return GroqProvider()
    if name == "bedrock":
        from packages.infrastructure.llm.bedrock_provider import BedrockProvider
        return BedrockProvider()
    if name == "ollama":
        from packages.infrastructure.llm.ollama_provider import OllamaProvider
        return OllamaProvider()
    raise ValueError(f"Unknown LLM provider '{name}'. Use one of {KNOWN_PROVIDERS}.")


def configured_chain() -> List[str]:
    primary = os.getenv("LLM_PROVIDER", "groq").strip().lower()
    chain = [primary]
    fallback_raw = os.getenv("LLM_FALLBACK_CHAIN", "ollama")
    for item in fallback_raw.split(","):
        name = item.strip().lower()
        if name and name not in chain:
            chain.append(name)
    return [n for n in chain if n in KNOWN_PROVIDERS] or ["groq", "ollama"]


class RoutedLLM(LLMProvider):
    name = "router"

    def __init__(self, providers: List[LLMProvider],
                 budget_fn: Callable[[], int] = daily_budget,
                 used_fn: Callable[[], Optional[int]] = tokens_used_today):
        if not providers:
            raise ValueError("RoutedLLM needs at least one provider")
        self.providers = providers
        self._budget_fn = budget_fn
        self._used_fn = used_fn

    def _check_budget(self) -> None:
        budget = self._budget_fn()
        if budget <= 0:
            return
        used = self._used_fn()
        if used is not None and used >= budget:
            raise LLMBudgetExceeded(f"Daily LLM token budget reached ({used}/{budget})")

    def chat(self, messages: List[Dict[str, str]], *, schema: Optional[Type[BaseModel]] = None,
             temperature: float = 0.1, max_tokens: int = 2048, purpose: str = "general") -> LLMResult:
        self._check_budget()
        errors: List[str] = []
        for provider in self.providers:
            try:
                return provider.chat(messages, schema=schema, temperature=temperature,
                                     max_tokens=max_tokens, purpose=purpose)
            except (LLMUnavailable, LLMSchemaError) as exc:
                errors.append(f"{provider.name}: {exc}")
                logger.warning("LLM provider %s failed (%s); trying next", provider.name, exc)
        raise LLMUnavailable("All LLM providers failed: " + " | ".join(errors))

    def healthcheck(self) -> Dict[str, Any]:
        results = [p.healthcheck() for p in self.providers]
        return {"ok": any(r.get("ok") for r in results), "providers": results}


_override: Optional[LLMProvider] = None
_override_lock = threading.Lock()


def set_llm_override(provider: Optional[LLMProvider]) -> None:
    """Test hook: force get_llm() to return `provider`."""
    global _override
    with _override_lock:
        _override = provider


def get_llm() -> LLMProvider:
    with _override_lock:
        if _override is not None:
            return _override
    providers: List[LLMProvider] = []
    for name in configured_chain():
        try:
            providers.append(_build(name))
        except Exception as exc:
            logger.warning("Could not build LLM provider %s: %s", name, exc)
    if not providers:
        raise LLMUnavailable("No LLM provider could be constructed")
    return RoutedLLM(providers)


async def generate_structured_json(prompt: str, system: Optional[str] = None,
                                   timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """
    Drop-in for ollama_client.generate_structured(): returns a dict or None.
    Used by llm_entity_resolver so it works with any configured provider.
    """
    from packages.infrastructure.llm.base import extract_json
    msgs: List[Dict[str, str]] = []
    if system:
        msgs.append({"role": "system", "content": system + "\nRespond with a single JSON object only."})
    msgs.append({"role": "user", "content": prompt})
    try:
        llm = get_llm()
        result = await llm.achat(msgs, temperature=0.1, max_tokens=1024, purpose="entity_adjudication")
        data = extract_json(result.text)
        return data if isinstance(data, dict) else None
    except (LLMError, ValueError) as exc:
        logger.debug("generate_structured_json returned None: %s", exc)
        return None
