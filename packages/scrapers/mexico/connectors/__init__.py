"""
Connectors package and connector registry factory.
Integrates official Mexican open-data portals, government registries, and B2B industrial directories.
"""

from typing import Dict, Type, Optional
from .base import SourceConnector
from .denue import DenueConnector
from .siem import SiemConnector
from .supplier_registry import SupplierRegistryConnector
from .datos_gob import DatosGobConnector
from .sat import SatConnector
from .rpc import RpcConnector
from .canacintra import CanacintraConnector
from .amcham import AmchamConnector
from .cosmos import CosmosConnector
from .quiminet import QuiminetConnector
from .seccion_amarilla import SeccionAmarillaConnector
from ..config.sources import SourceConfig, sources_registry


CONNECTOR_CLASSES: Dict[str, Type[SourceConnector]] = {
    # API & Open Data Connectors
    "denue": DenueConnector,
    "denue_bulk": DenueConnector,
    "denue_map": DenueConnector,
    "inegi_datos_abiertos": DenueConnector,
    "siem": SiemConnector,
    "supplier_registry": SupplierRegistryConnector,
    "supplier": SupplierRegistryConnector,
    "datos_gob": DatosGobConnector,
    "sat": SatConnector,
    "sat_validator": SatConnector,
    # Scraping Connectors
    "rpc": RpcConnector,
    "canacintra": CanacintraConnector,
    "amcham": AmchamConnector,
    "cosmos": CosmosConnector,
    "quiminet": QuiminetConnector,
    "seccion_amarilla": SeccionAmarillaConnector,
}

API_CONNECTOR_KEYS = ["denue", "siem", "datos_gob", "sat", "supplier_registry"]
SCRAPING_CONNECTOR_KEYS = ["canacintra", "amcham", "cosmos", "quiminet", "seccion_amarilla", "rpc"]


def get_connector(source_key: str, config: Optional[SourceConfig] = None) -> SourceConnector:
    """Factory creating an initialized SourceConnector instance."""
    cls = CONNECTOR_CLASSES.get(source_key.lower())
    if not cls:
        raise ValueError(f"Unknown source connector '{source_key}'. Available: {list(CONNECTOR_CLASSES.keys())}")
    
    cfg = config or sources_registry.get_source(source_key)
    if not cfg:
        cfg = SourceConfig(
            name=source_key.upper(),
            description=f"Source connector for {source_key}",
            enabled=True,
            type="api" if source_key.lower() in API_CONNECTOR_KEYS else "directory",
            category="api" if source_key.lower() in API_CONNECTOR_KEYS else "scraping",
            source_type="official_api" if source_key.lower() in API_CONNECTOR_KEYS else "public_directory",
        )
    return cls(cfg)
