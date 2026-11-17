"""
Secret redaction helpers.

`mask()` shows only the last 4 characters of a key.
`RedactingFilter` scrubs key-shaped strings from every log record so a key can
never reach a log file by accident.
"""

from __future__ import annotations

import logging
import re
from typing import Any

# Patterns of well-known credential formats.
_PATTERNS = [
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),                 # Groq
    re.compile(r"AKIA[0-9A-Z]{16}"),                     # AWS access key id
    re.compile(r"ASIA[0-9A-Z]{16}"),                     # AWS temporary access key id
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),               # OpenAI-style
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{20,}"),  # bearer tokens
]

REDACTED = "[REDACTED]"


def mask(value: str | None) -> str:
    """Return '****abcd' (last 4 chars) or '' for empty input."""
    if not value:
        return ""
    value = str(value)
    if len(value) <= 4:
        return "****"
    return "****" + value[-4:]


def redact_text(text: str) -> str:
    """Replace any credential-shaped substring in `text`."""
    if not text:
        return text
    out = text
    for pat in _PATTERNS:
        if pat.groups:
            out = pat.sub(lambda m: m.group(1) + REDACTED, out)
        else:
            out = pat.sub(REDACTED, out)
    return out


class RedactingFilter(logging.Filter):
    """Logging filter that redacts credentials in message and args."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        try:
            msg = record.getMessage()
            redacted = redact_text(msg)
            if redacted != msg:
                record.msg = redacted
                record.args = ()
        except Exception:
            # Never let a logging filter break the application.
            pass
        return True


_INSTALLED = False


def install_redaction() -> None:
    """Attach the filter to the root logger's handlers (idempotent).

    Filters on a logger do not apply to records propagated from child loggers,
    so the filter is attached to every handler. New handlers added later are
    covered because `logging.Handler.__init__` is wrapped once.
    """
    global _INSTALLED
    flt = RedactingFilter()
    root = logging.getLogger()
    for h in root.handlers:
        if not any(isinstance(f, RedactingFilter) for f in h.filters):
            h.addFilter(flt)
    if _INSTALLED:
        return
    _INSTALLED = True

    original_init = logging.Handler.__init__

    def patched_init(self, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        self.addFilter(RedactingFilter())

    logging.Handler.__init__ = patched_init  # type: ignore[method-assign]
