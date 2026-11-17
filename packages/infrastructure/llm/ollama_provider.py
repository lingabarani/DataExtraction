"""Local Ollama provider (kept so existing deployments behave as before)."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional, Type

import httpx
from pydantic import BaseModel, ValidationError

from packages.infrastructure.llm.base import (
    LLMProvider, LLMResult, LLMSchemaError, LLMUnavailable,
    parse_with_schema, schema_instruction,
)
from packages.infrastructure.llm.usage import record_usage

logger = logging.getLogger("dataextraction.llm.ollama")
_SCHEMA_RETRIES = 1


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, *, base_url: Optional[str] = None, model: Optional[str] = None,
                 transport: Optional[httpx.BaseTransport] = None, timeout: Optional[float] = None):
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        self._transport = transport
        self._timeout = timeout or float(os.getenv("OLLAMA_BATCH_TIMEOUT_SECONDS", "30"))

    def chat(self, messages: List[Dict[str, str]], *, schema: Optional[Type[BaseModel]] = None,
             temperature: float = 0.1, max_tokens: int = 2048, purpose: str = "general") -> LLMResult:
        msgs = list(messages)
        if schema is not None:
            msgs = [{"role": "system", "content": schema_instruction(schema)}] + msgs
        last_error: Optional[str] = None
        for _try in range(_SCHEMA_RETRIES + 1):
            payload: Dict[str, Any] = {
                "model": self.model, "messages": msgs, "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            }
            if schema is not None:
                payload["format"] = "json"
            started = time.perf_counter()
            try:
                with httpx.Client(timeout=self._timeout, transport=self._transport) as c:
                    resp = c.post(f"{self.base_url}/api/chat", json=payload)
                resp.raise_for_status()
            except Exception as exc:
                record_usage(provider="ollama", model=self.model, key_id=None, purpose=purpose,
                             prompt_tokens=0, completion_tokens=0,
                             latency_ms=int((time.perf_counter() - started) * 1000),
                             status_code=None, success=False)
                raise LLMUnavailable(f"Ollama unavailable: {type(exc).__name__}") from exc
            data = resp.json()
            text = (data.get("message") or {}).get("content", "")
            p_tok, c_tok = data.get("prompt_eval_count", 0), data.get("eval_count", 0)
            record_usage(provider="ollama", model=self.model, key_id=None, purpose=purpose,
                         prompt_tokens=p_tok, completion_tokens=c_tok,
                         latency_ms=int((time.perf_counter() - started) * 1000),
                         status_code=200, success=True)
            result = LLMResult(text=text, provider="ollama", model=self.model,
                               usage={"prompt_tokens": p_tok, "completion_tokens": c_tok})
            if schema is None:
                return result
            try:
                result.parsed = parse_with_schema(text, schema)
                return result
            except (ValueError, ValidationError) as exc:
                last_error = str(exc)[:300]
                msgs = msgs + [{"role": "assistant", "content": text[:2000]},
                               {"role": "user", "content": "Invalid: " + last_error + " Return ONLY corrected JSON."}]
        raise LLMSchemaError(f"Ollama did not return valid JSON for {schema.__name__}: {last_error}")

    def healthcheck(self) -> Dict[str, Any]:
        try:
            with httpx.Client(timeout=3.0, transport=self._transport) as c:
                r = c.get(f"{self.base_url}/api/tags")
            return {"ok": r.status_code == 200, "provider": "ollama", "model": self.model}
        except Exception as exc:
            return {"ok": False, "provider": "ollama", "model": self.model, "error": type(exc).__name__}
