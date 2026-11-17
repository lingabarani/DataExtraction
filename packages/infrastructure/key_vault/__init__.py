"""Secrets management: encrypted key store, rotation and redaction."""

from packages.infrastructure.key_vault.manager import (  # noqa: F401
    SecretsManager,
    get_secrets_manager,
    set_secrets_manager,
)
from packages.infrastructure.log_redaction import (  # noqa: F401
    RedactingFilter,
    install_redaction,
    mask,
    redact_text,
)
from packages.infrastructure.key_vault.store import DbKeyStore, KeyRecord  # noqa: F401

__all__ = [
    "SecretsManager", "get_secrets_manager", "set_secrets_manager",
    "RedactingFilter", "install_redaction", "mask", "redact_text",
    "DbKeyStore", "KeyRecord",
]

# Redact credentials from all log output as soon as the vault is imported.
install_redaction()
