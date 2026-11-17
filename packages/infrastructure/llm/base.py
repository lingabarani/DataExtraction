"""Provider-agnostic LLM interface, result types and errors."""

from __future__ import annotations

import asyncio
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, ValidationError


class LLMError(Exception):
    """Base class for LLM failures."""


class LLMUnavailable(LLMError):
    """No usable key / provider, or every provider in the chain failed."""


class LLMBudgetExceeded(LLMError):
    """The configured daily token budget is used up."""


class LLMSchemaError(LLMError):
    """The model kept returning output that does not match the requested schema."""


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    parsed: Optional[BaseModel] = None
    usage: Dict[str, int] = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        schema: Optional[Type[BaseModel]] = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        purpose: str = "general",
    ) -> LLMResult:
        """Run a chat completion. When `schema` is given, `result.parsed` is a validated instance."""

    @abstractmethod
    def healthcheck(self) -> Dict[str, Any]:
        """Return {"ok": bool, ...}. Must be cheap and must not raise."""

    async def achat(self, messages, **kwargs) -> LLMResult:
        return await asyncio.to_thread(self.chat, messages, **kwargs)


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def extract_json(text: str) -> Any:
    """Parse JSON from model output, tolerating code fences and surrounding prose."""
    if text is None:
        raise ValueError("empty model output")
    cleaned = _FENCE_RE.sub("", text.strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost {...} or [...] block.
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start, end = cleaned.find(open_c), cleaned.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("no valid JSON found in model output")


def parse_with_schema(text: str, schema: Type[BaseModel]) -> BaseModel:
    """Validate model text against a pydantic model. Raises ValueError/ValidationError."""
    data = extract_json(text)
    return schema.model_validate(data)


def schema_instruction(schema: Type[BaseModel]) -> str:
    return (
        "Respond with ONLY a JSON object that matches this JSON Schema. No prose, no code fences.\n"
        + json.dumps(schema.model_json_schema())
    )


__all__ = [
    "LLMError", "LLMUnavailable", "LLMBudgetExceeded", "LLMSchemaError",
    "LLMResult", "LLMProvider", "extract_json", "parse_with_schema", "schema_instruction",
    "ValidationError",
]
