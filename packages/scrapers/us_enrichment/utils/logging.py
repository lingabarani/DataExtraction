"""
Structured logging module for the US B2B Ingestion Pipeline.
"""

import logging
import sys
from pathlib import Path
from typing import Optional, Any


class StructuredLogger:
    def __init__(self, name: str = "us_b2b", log_file: Optional[Path] = None, level: int = logging.INFO):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        self.logger.propagate = False
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.logger.handlers = []
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

    def _format_kv(self, kwargs: dict) -> str:
        return " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)

    def info(self, message: Optional[str] = None, **kwargs: Any) -> None:
        full = f"{message} {self._format_kv(kwargs)}".strip() if message else self._format_kv(kwargs)
        self.logger.info(full)

    def warn(self, message: Optional[str] = None, **kwargs: Any) -> None:
        full = f"{message} {self._format_kv(kwargs)}".strip() if message else self._format_kv(kwargs)
        self.logger.warning(full)

    def warning(self, message: Optional[str] = None, **kwargs: Any) -> None:
        self.warn(message, **kwargs)

    def error(self, message: Optional[str] = None, **kwargs: Any) -> None:
        full = f"{message} {self._format_kv(kwargs)}".strip() if message else self._format_kv(kwargs)
        self.logger.error(full)

    def debug(self, message: Optional[str] = None, **kwargs: Any) -> None:
        full = f"{message} {self._format_kv(kwargs)}".strip() if message else self._format_kv(kwargs)
        self.logger.debug(full)


def get_pipeline_logger(log_type: str = "ingestion") -> StructuredLogger:
    from ..config.settings import settings
    log_file = settings.API_LOGS_DIR / f"us_{log_type}.log"
    return StructuredLogger(name=f"us_b2b.{log_type}", log_file=log_file)


logger = StructuredLogger()
