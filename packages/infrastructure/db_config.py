"""
DataExtraction — Database Configuration Bridge
Sourced dynamically from ConfigManager (AWS Secrets Manager / Environment).
Eliminates hardcoded credentials and centralizes connection management.
"""
import sys
from pathlib import Path

# Ensure packages/infrastructure is importable when this file is used directly
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from packages.infrastructure.config_manager import config_manager

POSTGRES_CONFIG = config_manager.get_database_config()
DATABASE_URL = config_manager.get_database_url()
ACTIVE_DB = config_manager.get("DATABASE_TYPE", "postgresql")
SQLITE_URL = config_manager.get("SQLITE_URL", "sqlite:///output/us/api/dataextraction.db")

__all__ = [
    "POSTGRES_CONFIG",
    "DATABASE_URL",
    "ACTIVE_DB",
    "SQLITE_URL",
]
