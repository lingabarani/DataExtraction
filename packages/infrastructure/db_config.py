"""
OneExtraction — Database Configuration Bridge
Sourced dynamically from ConfigManager (AWS Secrets Manager / Environment).
Eliminates hardcoded credentials and centralizes connection management.
"""

from config_manager import config_manager

POSTGRES_CONFIG = config_manager.get_database_config()
DATABASE_URL = config_manager.get_database_url()
ACTIVE_DB = config_manager.get("DATABASE_TYPE", "postgresql")
SQLITE_URL = config_manager.get("SQLITE_URL", "sqlite:///output/us/api/oneextraction.db")

__all__ = [
    "POSTGRES_CONFIG",
    "DATABASE_URL",
    "ACTIVE_DB",
    "SQLITE_URL",
]
