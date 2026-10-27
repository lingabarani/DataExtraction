"""
Raw data preservation and incremental processing storage manager.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any
from ..config.settings import settings
from ..utils.hashing import sha256_file, sha256_text
from ..utils.logging import logger


class RawStorage:
    """
    Manages raw source file persistence under data/raw/{source}/{date}/.
    Stores raw files, metadata, and SHA-256 checksums to guarantee auditability
    and enable incremental processing.
    """

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or settings.RAW_DATA_DIR

    def get_source_date_dir(self, source_name: str, date_str: Optional[str] = None) -> Path:
        if not date_str:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        target_dir = self.base_dir / source_name.lower() / date_str
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir

    def save_raw_file(
        self,
        source_name: str,
        filename: str,
        content_bytes: bytes,
        source_url: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Saves raw byte stream with metadata and SHA-256 checksum."""
        date_dir = self.get_source_date_dir(source_name)
        target_file = date_dir / filename
        
        with open(target_file, "wb") as f:
            f.write(content_bytes)

        checksum = sha256_file(str(target_file))
        meta_payload = {
            "source": source_name,
            "filename": filename,
            "filepath": str(target_file),
            "source_url": source_url,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "sha256": checksum,
            "byte_size": len(content_bytes),
            "custom_metadata": metadata or {},
        }

        meta_file = date_dir / f"{filename}.meta.json"
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta_payload, f, indent=2)

        logger.info(
            f"Preserved raw source file",
            source=source_name,
            file=filename,
            sha256=checksum[:12],
            bytes=len(content_bytes),
        )
        return meta_payload

    def save_raw_text(
        self,
        source_name: str,
        filename: str,
        text_content: str,
        source_url: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Saves raw text/JSON content."""
        return self.save_raw_file(
            source_name=source_name,
            filename=filename,
            content_bytes=text_content.encode("utf-8"),
            source_url=source_url,
            metadata=metadata,
        )

    def is_cached_today(self, source_name: str, filename: str) -> Optional[Path]:
        """Checks if a raw file was already retrieved today for incremental skip."""
        date_dir = self.get_source_date_dir(source_name)
        target_file = date_dir / filename
        if target_file.exists() and target_file.stat().st_size > 0:
            return target_file
        return None


raw_storage = RawStorage()
