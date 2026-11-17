"""
Groq provider (OpenAI-compatible endpoint) for gpt-oss models.

Key handling: the API key is fetched from the SecretsManager on every call, so a
key added today is used immediately. 401/403 mark a key invalid and switch to the
next one; a long 429 puts the key in cooldown and switches.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional, Type

import httpx
from pydantic import BaseModel, ValidationError

from packages.infrastructure.key_vault import SecretsManager, get_secrets_manager
from packages.infrastructure.llm.base import (
    LLMProvider, LLMResult, LLMSchemaError, LLMUnavailable,
    parse_with_schema, schema_instruction,
)
from packages.infrastructure.llm.usage import record_usage

logger = logging.getLogger("dataextraction.llm.groq")

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_FALLBACK_MODEL = "openai/gpt-oss-20b"

_MAX_ATTEMPTS = 6
_MAX_SHORT_RATE_WAIT_S = 10.0
_SCHEMA_RETRIES = 2


def _retry_after_seconds(resp: httpx.Response) -> Optional[float]:
    raw = resp.headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(
        self,
        *,
        secrets: Optional[SecretsManager] = None,
        model: Optional[str] = None,
        fallback_model: Optional[str] = None,
        base_url: str = GROQ_BASE_URL,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
        strict_schema: Optional[bool] = None,
    ):
        self._secrets = secrets
        self.model = model or os.getenv("GROQ_MODEL", DEFAULT_MODEL)
        self.fallback_model = fallback_model or os.getenv("GROQ_FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL)
        self.base_url = base_url.rstrip("/")
        self._transport = transport
        self._sleep = sleep
        self._strict = (os.getenv("GROQ_STRICT_SCHEMA", "false").lower() == "true"
                        if strict_schema is None else strict_schema)
        self._reasoning_effort = os.getenv("GROQ_REASONING_EFFORT", "low")

    @property
    def secrets(self) -> SecretsManager:
        return self._secrets or get_secrets_manager()

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=httpx.Timeout(60.0, connect=5.0), transport=self._transport)

    # ── single HTTP call with key rotation ───────────────────────────────────
    def _post(self, payload: Dict[str, Any], purpose: str) -> Dict[str, Any]:
        """POST with key rotation, rate-limit waits and model fallback. Returns the JSON body."""
        attempts = 0
        server_errors = 0
        short_waits = 0
        model_switched = False
        last_status: Optional[int] = None

        while attempts < _MAX_ATTEMPTS:
            attempts += 1
            key = self.secrets.get_active_key("groq")
            if key is None:
                raise LLMUnavailable(
                    "No usable Groq API key. Add one in Settings > API Keys or set GROQ_API_KEY."
                    + (f" (last HTTP status: {last_status})" if last_status else "")
                )
            started = time.perf_counter()
            try:
                with self._client() as client:
                    resp = client.post(
                        f"{self.base_url}/chat/completions",
                        json=payload,
                        headers={"Authorization": f"Bearer {key.value}", "Content-Type": "application/json"},
                    )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                server_errors += 1
                record_usage(provider="groq", model=payload["model"], key_id=key.id, purpose=purpose,
                             prompt_tokens=0, completion_tokens=0,
                             latency_ms=int((time.perf_counter() - started) * 1000),
                             status_code=None, success=False)
                if server_errors >= 3:
                    raise LLMUnavailable(f"Groq network error: {type(exc).__name__}") from exc
                self._sleep(min(2.0 * server_errors, 8.0))
                continue

            latency_ms = int((time.perf_counter() - started) * 1000)
            status = resp.status_code
            last_status = status

            if status == 200:
                body = resp.json()
                usage = body.get("usage") or {}
                self.secrets.mark_used(key)
                record_usage(provider="groq", model=payload["model"], key_id=key.id, purpose=purpose,
                             prompt_tokens=usage.get("prompt_tokens", 0),
                             completion_tokens=usage.get("completion_tokens", 0),
                             latency_ms=latency_ms, status_code=200, success=True)
                return body

            record_usage(provider="groq", model=payload["model"], key_id=key.id, purpose=purpose,
                         prompt_tokens=0, completion_tokens=0, latency_ms=latency_ms,
                         status_code=status, success=False)

            if status in (401, 403):
                self.secrets.report_failure(key, status)
                continue  # next key, if any

            if status == 429:
                retry_after = _retry_after_seconds(resp)
                if retry_after is not None and retry_after <= _MAX_SHORT_RATE_WAIT_S and short_waits < 3:
                    short_waits += 1
                    self._sleep(retry_after)
                    continue
                self.secrets.report_failure(key, 429, retry_after)
                continue

            if status >= 500:
                server_errors += 1
                if server_errors >= 3:
                    raise LLMUnavailable(f"Groq server error HTTP {status}")
                self._sleep(min(2.0 ** server_errors, 8.0))
                continue

            if status in (400, 404) and not model_switched and payload["model"] != self.fallback_model:
                text = resp.text.lower()
                if "model" in text and ("not found" in text or "decommission" in text or "does not exist" in text):
                    logger.warning("Model %s rejected; switching to %s", payload["model"], self.fallback_model)
                    payload = {**payload, "model": self.fallback_model}
                    model_switched = True
                    continue

            # Other 4xx: caller decides (e.g. 400 for response_format).
            raise _HttpStatusError(status, resp.text[:300])

        raise LLMUnavailable(f"Groq request failed after {attempts} attempts (last HTTP status {last_status})")

    # ── public API ───────────────────────────────────────────────────────────
    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        schema: Optional[Type[BaseModel]] = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        purpose: str = "general",
    ) -> LLMResult:
        msgs = list(messages)
        use_response_format = schema is not None

        last_error: Optional[str] = None
        for schema_try in range(_SCHEMA_RETRIES + 1):
            payload: Dict[str, Any] = {
                "model": self.model,
                "messages": msgs,
                "temperature": temperature,
                "max_completion_tokens": max_tokens,
            }
            if "gpt-oss" in self.model:
                payload["reasoning_effort"] = self._reasoning_effort
            if schema is not None and use_response_format:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": schema.__name__[:60], "strict": self._strict,
                                    "schema": schema.model_json_schema()},
                }
            try:
                body = self._post(payload, purpose)
            except _HttpStatusError as exc:
                if exc.status == 400 and schema is not None and use_response_format:
                    # Schema not accepted by the endpoint: fall back to prompt-based JSON.
                    logger.info("response_format rejected (%s); using prompt-based JSON", exc.detail[:120])
                    use_response_format = False
                    msgs = [{"role": "system", "content": schema_instruction(schema)}] + list(messages)
                    continue
                raise LLMUnavailable(f"Groq HTTP {exc.status}: {exc.detail}") from exc

            choice = (body.get("choices") or [{}])[0]
            text = ((choice.get("message") or {}).get("content")) or ""
            usage = body.get("usage") or {}
            result = LLMResult(
                text=text, provider="groq", model=body.get("model", payload["model"]),
                usage={"prompt_tokens": usage.get("prompt_tokens", 0),
                       "completion_tokens": usage.get("completion_tokens", 0)},
            )
            if schema is None:
                return result
            try:
                result.parsed = parse_with_schema(text, schema)
                return result
            except (ValueError, ValidationError) as exc:
                last_error = str(exc)[:300]
                logger.info("Model output failed schema validation (try %d): %s", schema_try + 1, last_error)
                msgs = msgs + [
                    {"role": "assistant", "content": text[:2000]},
                    {"role": "user", "content": "That output was invalid: " + last_error +
                     " Return ONLY corrected JSON that matches the schema."},
                ]
        raise LLMSchemaError(f"Model did not return valid JSON for {schema.__name__}: {last_error}")

    def healthcheck(self) -> Dict[str, Any]:
        key = self.secrets.get_active_key("groq")
        if key is None:
            return {"ok": False, "provider": "groq", "model": self.model, "error": "no usable API key"}
        try:
            r = self.chat([{"role": "user", "content": "Reply with the single word: ok"}],
                          max_tokens=256, purpose="healthcheck")
            return {"ok": True, "provider": "groq", "model": r.model}
        except Exception as exc:
            return {"ok": False, "provider": "groq", "model": self.model, "error": str(exc)[:200]}


def probe_groq_key(
    value: str,
    *,
    model: Optional[str] = None,
    transport: Optional[httpx.BaseTransport] = None,
    base_url: str = GROQ_BASE_URL,
) -> Dict[str, Any]:
    """Check one specific key with a tiny request. Never raises; never logs the key."""
    mdl = model or os.getenv("GROQ_MODEL", DEFAULT_MODEL)
    try:
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0), transport=transport) as client:
            resp = client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                json={"model": mdl, "messages": [{"role": "user", "content": "ok"}],
                      "max_completion_tokens": 16},
                headers={"Authorization": f"Bearer {value}"},
            )
        return {"ok": resp.status_code == 200, "status_code": resp.status_code, "model": mdl}
    except Exception as exc:
        return {"ok": False, "status_code": None, "model": mdl, "error": type(exc).__name__}


class _HttpStatusError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.detail = detail
