"""
RPC / SIGER (Registro Público de Comercio - Secretaría de Economía) Connector.
Legal verification connector. Adheres to compliance boundary by disabling automated bulk scraping.
"""

from typing import List, Dict, Any, Optional
from .base import SourceConnector
from ..models.company import CanonicalCompany
from ..models.source_record import RawSourcePayload, SourceProvenanceRecord
from ..pipeline.normalization import normalize_company_name
from ..utils.hashing import generate_entity_fingerprint, generate_company_id
from ..utils.logging import logger


class RpcConnector(SourceConnector):
    """
    RPC / SIGER Connector.
    Note: Bulk automated extraction is disabled per compliance rules.
    This connector serves as a legal verification interface template for authorized queries.
    """

    def fetch(self, limit: Optional[int] = None) -> List[RawSourcePayload]:
        if not self.config.is_bulk_enabled or not self.config.enabled:
            logger.info(
                "RPC / SIGER connector is configured for legal verification only; automated bulk extraction is disabled.",
                source="RPC",
                compliance_status="ACCESS_RESTRICTED_BY_POLICY",
            )
            return []
        
        # If enabled in authorized/licensed mode in the future:
        return []

    def parse(self, payload: RawSourcePayload) -> Dict[str, Any]:
        d = payload.raw_data
        return {
            "folio_mercantil": d.get("folio_mercantil"),
            "legal_name": d.get("denominacion_razon_social"),
            "state": d.get("estado"),
            "registration_date": d.get("fecha_constitucion"),
        }

    def normalize(self, parsed: Dict[str, Any], provenance: SourceProvenanceRecord) -> CanonicalCompany:
        legal_orig, legal_norm = normalize_company_name(parsed.get("legal_name"))
        fp = generate_entity_fingerprint(normalized_name=legal_norm, state=parsed.get("state"))
        comp_id = generate_company_id(fp)

        return CanonicalCompany(
            company_id=comp_id,
            legal_name=legal_orig,
            normalized_name=legal_norm,
            source_records=[provenance],
            source_count=1,
            entity_fingerprint=fp,
            last_verified_at=provenance.retrieved_at,
        )
