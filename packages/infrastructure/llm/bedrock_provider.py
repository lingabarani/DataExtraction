"""
AWS Bedrock provider (Converse API). boto3 is imported lazily so the platform runs
without it. Credentials: SecretsManager provider "aws" (JSON in the key value:
{"access_key_id": "...", "secret_access_key": "...", "session_token": "..."}) or the
default boto3 credential chain (IAM role, env vars, shared config).
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, ValidationError

from packages.infrastructure.key_vault import SecretsManager, get_secrets_manager
from packages.infrastructure.llm.base import (
    LLMProvider, LLMResult, LLMSchemaError, LLMUnavailable,
    parse_with_schema, schema_instruction,
)
from packages.infrastructure.llm.usage import record_usage

logger = logging.getLogger("dataextraction.llm.bedrock")

DEFAULT_MODEL_ID = "openai.gpt-oss-120b-1:0"
_SCHEMA_RETRIES = 2


class BedrockProvider(LLMProvider):
    name = "bedrock"

    def __init__(self, *, secrets: Optional[SecretsManager] = None, model_id: Optional[str] = None,
                 region: Optional[str] = None, client: Any = None):
        self._secrets = secrets
        self.model = model_id or os.getenv("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID)
        self.region = region or os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
        self._client = client  # injectable for tests

    @property
    def secrets(self) -> SecretsManager:
        return self._secrets or get_secrets_manager()

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3  # lazy import
        except ImportError as exc:
            raise LLMUnavailable("boto3 is not installed; cannot use the Bedrock provider") from exc

        kwargs: Dict[str, Any] = {"region_name": self.region}
        rec = self.secrets.get_active_key("aws")
        if rec is not None:
            try:
                creds = json.loads(rec.value)
                kwargs.update(
                    aws_access_key_id=creds["access_key_id"],
                    aws_secret_access_key=creds["secret_access_key"],
                )
                if creds.get("session_token"):
                    kwargs["aws_session_token"] = creds["session_token"]
            except (ValueError, KeyError):
                logger.warning("Stored AWS credential is not valid JSON with access_key_id/secret_access_key; "
                               "falling back to the default boto3 credential chain.")
        return boto3.client("bedrock-runtime", **kwargs)

    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        schema: Optional[Type[BaseModel]] = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        purpose: str = "general",
    ) -> LLMResult:
        client = self._get_client()
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        if schema is not None:
            system_parts.append(schema_instruction(schema))
        convo = [
            {"role": m["role"], "content": [{"text": m["content"]}]}
            for m in messages if m["role"] in ("user", "assistant")
        ]

        last_error: Optional[str] = None
        for _try in range(_SCHEMA_RETRIES + 1):
            started = time.perf_counter()
            try:
                kwargs: Dict[str, Any] = {
                    "modelId": self.model,
                    "messages": convo,
                    "inferenceConfig": {"temperature": temperature, "maxTokens": max_tokens},
                }
                if system_parts:
                    kwargs["system"] = [{"text": "\n\n".join(system_parts)}]
                resp = client.converse(**kwargs)
            except Exception as exc:
                record_usage(provider="bedrock", model=self.model, key_id=None, purpose=purpose,
                             prompt_tokens=0, completion_tokens=0,
                             latency_ms=int((time.perf_counter() - started) * 1000),
                             status_code=None, success=False)
                raise LLMUnavailable(f"Bedrock call failed: {type(exc).__name__}: {str(exc)[:200]}") from exc

            blocks = (((resp.get("output") or {}).get("message") or {}).get("content")) or []
            text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
            usage = resp.get("usage") or {}
            p_tok, c_tok = usage.get("inputTokens", 0), usage.get("outputTokens", 0)
            record_usage(provider="bedrock", model=self.model, key_id=None, purpose=purpose,
                         prompt_tokens=p_tok, completion_tokens=c_tok,
                         latency_ms=int((time.perf_counter() - started) * 1000),
                         status_code=200, success=True)
            result = LLMResult(text=text, provider="bedrock", model=self.model,
                               usage={"prompt_tokens": p_tok, "completion_tokens": c_tok})
            if schema is None:
                return result
            try:
                result.parsed = parse_with_schema(text, schema)
                return result
            except (ValueError, ValidationError) as exc:
                last_error = str(exc)[:300]
                convo = convo + [
                    {"role": "assistant", "content": [{"text": text[:2000]}]},
                    {"role": "user", "content": [{"text": "Invalid output: " + last_error +
                                                  " Return ONLY corrected JSON."}]},
                ]
        raise LLMSchemaError(f"Bedrock did not return valid JSON for {schema.__name__}: {last_error}")

    def healthcheck(self) -> Dict[str, Any]:
        try:
            r = self.chat([{"role": "user", "content": "Reply with the single word: ok"}],
                          max_tokens=64, purpose="healthcheck")
            return {"ok": True, "provider": "bedrock", "model": r.model}
        except Exception as exc:
            return {"ok": False, "provider": "bedrock", "model": self.model, "error": str(exc)[:200]}
