"""
SecretsManager: one place to ask "which API key should I use right now?".

Backends, in priority order:
  1. Encrypted DB store (keys entered through the API / dashboard)
  2. AWS Secrets Manager (when USE_AWS_SECRETS=true)
  3. Environment variables (GROQ_API_KEY, GROQ_API_KEYS=k1,k2 ...)

Rotation rules:
  * 401/403 -> key is marked invalid and skipped from then on.
  * 429     -> key goes into cooldown (Retry-After, default 60 s).
  * New keys are visible on the next call (cache TTL is a few seconds and is
    cleared on every write), so no restart is needed.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from packages.infrastructure.key_vault.store import DbKeyStore, KeyRecord

logger = logging.getLogger("dataextraction.secrets")

_CACHE_TTL_S = float(os.getenv("SECRETS_CACHE_TTL_SECONDS", "5"))
_DEFAULT_COOLDOWN_S = 60

# Environment variable names per provider.
_ENV_NAMES = {
    "groq": ("GROQ_API_KEY", "GROQ_API_KEYS"),
    "aws": ("AWS_ACCESS_KEY_ID",),
    "linkedin": ("LINKEDIN_COOKIE", "LINKEDIN_COOKIES"),
    "search": ("SEARCH_API_KEY", "BRAVE_API_KEY", "TAVILY_API_KEY", "SERPAPI_API_KEY"),
}


def _truthy(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes", "on")


class SecretsManager:
    def __init__(self, db_store: Optional[DbKeyStore] = None, clock=time.monotonic):
        self._db_store = db_store
        self._db_store_init = db_store is not None
        self._clock = clock
        self._lock = threading.RLock()
        self._cache: Dict[str, tuple] = {}                 # provider -> (expires_monotonic, [KeyRecord])
        self._mem_state: Dict[str, Dict[str, Any]] = {}    # key id -> {"invalid": bool, "cooldown_until": float}
        self._mem_last_used: Dict[str, float] = {}

    # ── internal ─────────────────────────────────────────────────────────────
    def _store(self) -> Optional[DbKeyStore]:
        if self._db_store is None and not self._db_store_init:
            self._db_store_init = True
            try:
                self._db_store = DbKeyStore()
            except Exception as exc:  # pragma: no cover
                logger.warning("DB key store unavailable: %s", exc)
        return self._db_store

    def invalidate_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def _env_keys(self, provider: str) -> List[KeyRecord]:
        names = _ENV_NAMES.get(provider, (f"{provider.upper()}_API_KEY", f"{provider.upper()}_API_KEYS"))
        values: List[str] = []
        for name in names:
            raw = os.getenv(name, "")
            if not raw:
                continue
            if name.endswith("KEYS") or name.endswith("_KEYS"):
                values.extend(v.strip() for v in raw.split(",") if v.strip())
            elif provider != "aws":
                values.append(raw.strip())
        seen, out = set(), []
        for idx, v in enumerate(values):
            if v in seen:
                continue
            seen.add(v)
            out.append(KeyRecord(id=f"env:{provider}:{idx}", provider=provider, value=v,
                                 label="environment", priority=1000 + idx, source="env"))
        return out

    def _aws_keys(self, provider: str) -> List[KeyRecord]:
        if not _truthy("USE_AWS_SECRETS"):
            return []
        try:
            from packages.infrastructure.config_manager import config_manager
            secrets = config_manager._fetch_aws_secrets()
        except Exception as exc:
            logger.warning("AWS Secrets Manager lookup failed: %s", exc)
            return []
        names = _ENV_NAMES.get(provider, (f"{provider.upper()}_API_KEY", f"{provider.upper()}_API_KEYS"))
        out: List[KeyRecord] = []
        idx = 0
        for name in names:
            raw = secrets.get(name)
            if not raw:
                continue
            parts = [p.strip() for p in str(raw).split(",")] if name.endswith("KEYS") else [str(raw).strip()]
            for v in parts:
                if v:
                    out.append(KeyRecord(id=f"aws:{provider}:{idx}", provider=provider, value=v,
                                         label="aws-secrets-manager", priority=500 + idx, source="aws"))
                    idx += 1
        return out

    def _candidates(self, provider: str) -> List[KeyRecord]:
        now = self._clock()
        with self._lock:
            cached = self._cache.get(provider)
            if cached and cached[0] > now:
                keys = list(cached[1])
            else:
                keys = []
                store = self._store()
                if store is not None:
                    try:
                        keys.extend(store.usable_keys(provider))
                    except Exception as exc:
                        logger.warning("Could not read keys from DB store: %s", exc)
                keys.extend(self._aws_keys(provider))
                keys.extend(self._env_keys(provider))
                self._cache[provider] = (now + _CACHE_TTL_S, list(keys))
            # Apply in-memory state for non-DB keys (DB keys already filtered in SQL).
            usable = []
            for k in keys:
                st = self._mem_state.get(k.id)
                if st:
                    if st.get("invalid"):
                        continue
                    if st.get("cooldown_until", 0) > now:
                        continue
                usable.append(k)
            return usable

    # ── public API ───────────────────────────────────────────────────────────
    def get_active_key(self, provider: str) -> Optional[KeyRecord]:
        """Best usable key: backend rank, then priority, then least recently used."""
        keys = self._candidates(provider)
        if not keys:
            return None
        rank = {"db": 0, "aws": 1, "env": 2}

        def sort_key(k: KeyRecord):
            lu = self._mem_last_used.get(k.id)
            if lu is None and k.last_used_at is not None:
                lu = k.last_used_at.timestamp() if isinstance(k.last_used_at, datetime) else 0.0
            return (rank.get(k.source, 9), k.priority, lu if lu is not None else -1.0)

        best = sorted(keys, key=sort_key)[0]
        return best

    def mark_used(self, key: KeyRecord) -> None:
        self._mem_last_used[key.id] = time.time()
        if key.source == "db":
            store = self._store()
            if store:
                try:
                    store.mark_used(key.id)
                except Exception as exc:
                    logger.debug("mark_used failed: %s", exc)

    def report_failure(self, key: KeyRecord, status_code: Optional[int],
                       retry_after: Optional[float] = None) -> None:
        """Called by providers after an auth or rate-limit error."""
        cooldown = int(retry_after) if retry_after and retry_after > 0 else _DEFAULT_COOLDOWN_S
        if key.source == "db":
            store = self._store()
            if store:
                try:
                    store.mark_failed(key.id, status_code, cooldown)
                except Exception as exc:
                    logger.warning("Could not record key failure: %s", exc)
        else:
            with self._lock:
                st = self._mem_state.setdefault(key.id, {})
                if status_code in (401, 403):
                    st["invalid"] = True
                elif status_code == 429:
                    st["cooldown_until"] = self._clock() + cooldown
        self.invalidate_cache()
        logger.warning("API key %s (%s) reported failure status=%s", key.label or key.id, key.provider,
                       status_code)

    # ── admin operations (used by the API router) ────────────────────────────
    def add_key(self, provider: str, value: str, label: str = "", priority: int = 100,
                expires_at: Optional[datetime] = None, created_by: Optional[str] = None) -> str:
        store = self._store()
        if store is None:
            raise RuntimeError("Database key store is not available")
        key_id = store.add_key(provider, value, label=label, priority=priority,
                               expires_at=expires_at, created_by=created_by)
        self.invalidate_cache()
        return key_id

    def list_keys(self, provider: Optional[str] = None) -> List[Dict[str, Any]]:
        store = self._store()
        return store.list_keys(provider) if store else []

    def update_key(self, key_id: str, **kwargs) -> bool:
        store = self._store()
        ok = store.update_key(key_id, **kwargs) if store else False
        self.invalidate_cache()
        return ok

    def delete_key(self, key_id: str) -> bool:
        store = self._store()
        ok = store.delete_key(key_id) if store else False
        self.invalidate_cache()
        return ok

    def get_key_by_id(self, key_id: str) -> Optional[KeyRecord]:
        store = self._store()
        return store.get_key(key_id) if store else None


_default_manager: Optional[SecretsManager] = None
_default_lock = threading.Lock()


def get_secrets_manager() -> SecretsManager:
    global _default_manager
    with _default_lock:
        if _default_manager is None:
            _default_manager = SecretsManager()
        return _default_manager


def set_secrets_manager(manager: Optional[SecretsManager]) -> None:
    """Test hook."""
    global _default_manager
    with _default_lock:
        _default_manager = manager
