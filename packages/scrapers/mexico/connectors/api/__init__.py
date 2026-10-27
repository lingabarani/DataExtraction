"""
API Connectors package.
Contains official government APIs and structured open data catalog connectors.
"""

from ..denue import DenueConnector
from ..siem import SiemConnector
from ..sat import SatConnector
from ..supplier_registry import SupplierRegistryConnector
from ..datos_gob import DatosGobConnector

__all__ = [
    "DenueConnector",
    "SiemConnector",
    "SatConnector",
    "SupplierRegistryConnector",
    "DatosGobConnector",
]
