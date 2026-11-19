"""DataExtraction — LLM status router (provider, model, key availability, token budget)."""

import os
from typing import Any, Dict

from fastapi import APIRouter, Depends, Query

from packages.api.dependencies import UserPrincipal, require_admin
from packages.infrastructure.llm.router import configured_chain
from packages.infrastructure.llm.usage import budget_status

router = APIRouter(prefix="/api/v1/llm", tags=["LLM"])


@router.get("/status")
def llm_status(check: bool = Query(False, description="Run a live health check (uses a few tokens)"),
               _admin: UserPrincipal = Depends(require_admin)) -> Dict[str, Any]:
    from packages.infrastructure.key_vault import get_secrets_manager
    chain = configured_chain()
    mgr = get_secrets_manager()
    groq_key = mgr.get_active_key("groq")
    out: Dict[str, Any] = {
        "provider": chain[0],
        "fallback_chain": chain[1:],
        "models": {
            "groq": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            "bedrock": os.getenv("BEDROCK_MODEL_ID", "openai.gpt-oss-120b-1:0"),
            "ollama": os.getenv("OLLAMA_MODEL", "llama3.1:8b"),
        },
        "groq_key_available": groq_key is not None,
        "groq_key_source": groq_key.source if groq_key else None,
        "groq_key_masked": ("****" + groq_key.value[-4:]) if groq_key else None,
        "budget": budget_status(),
    }
    if check:
        from packages.infrastructure.llm import get_llm
        out["health"] = get_llm().healthcheck()
    return out
