"""Fernet encryption for stored API keys. Master key comes from SECRETS_MASTER_KEY."""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

try:
    from packages.infrastructure.config_manager import ConfigurationError
except Exception:  # pragma: no cover - config_manager import should always work
    class ConfigurationError(Exception):  # type: ignore[no-redef]
        pass


def _fernet() -> Fernet:
    raw = os.getenv("SECRETS_MASTER_KEY", "").strip()
    if not raw:
        raise ConfigurationError(
            "SECRETS_MASTER_KEY is not set. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(raw.encode("utf-8"))
    except Exception as exc:
        raise ConfigurationError(f"SECRETS_MASTER_KEY is not a valid Fernet key: {exc}") from exc


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ConfigurationError(
            "Stored key could not be decrypted. SECRETS_MASTER_KEY changed or data is corrupt."
        ) from exc
