"""
Structured logging module for the Mexico B2B Ingestion Pipeline.
Supports console logging and dedicated file loggers for API and Scraping channels.
"""

import logging
import sys
from pathlib import Path
from typing import Optional, Any


class StructuredLogger:
    def __init__(self, name: str = "mexico_b2b", log_file: Optional[Path] = None, level: int = logging.INFO):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        self.logger.propagate = False

        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Clear existing handlers to avoid duplicates on re-init
        self.logger.handlers = []

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        # Optional file handler
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

    def _format_kv(self, kwargs: dict) -> str:
        parts = []
        for k, v in kwargs.items():
            if v is not None:
                parts.append(f"{k}={v}")
        return " ".join(parts)

    def info(self, message: Optional[str] = None, **kwargs: Any) -> None:
        formatted = self._format_kv(kwargs)
        full_msg = f"{message} {formatted}".strip() if message else formatted
        self.logger.info(full_msg)

    def warn(self, message: Optional[str] = None, **kwargs: Any) -> None:
        formatted = self._format_kv(kwargs)
        full_msg = f"{message} {formatted}".strip() if message else formatted
        self.logger.warning(full_msg)

    def warning(self, message: Optional[str] = None, **kwargs: Any) -> None:
        self.warn(message, **kwargs)

    def error(self, message: Optional[str] = None, **kwargs: Any) -> None:
        formatted = self._format_kv(kwargs)
        full_msg = f"{message} {formatted}".strip() if message else formatted
        self.logger.error(full_msg)

    def debug(self, message: Optional[str] = None, **kwargs: Any) -> None:
        formatted = self._format_kv(kwargs)
        full_msg = f"{message} {formatted}".strip() if message else formatted
        self.logger.debug(full_msg)


def get_channel_logger(channel: str, log_type: str = "ingestion") -> StructuredLogger:
    """
    Creates a dedicated StructuredLogger writing to output/{channel}/logs/{channel}_{log_type}.log.
    """
    from ..config.settings import settings
    channel_clean = channel.lower()
    log_dir = settings.API_LOGS_DIR if channel_clean == "api" else settings.SCRAPING_LOGS_DIR
    log_file = log_dir / f"{channel_clean}_{log_type}.log"
    return StructuredLogger(name=f"mexico_b2b.{channel_clean}.{log_type}", log_file=log_file)


logger = StructuredLogger()
