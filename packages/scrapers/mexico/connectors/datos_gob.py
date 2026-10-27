"""
datos.gob.mx Open-Data Catalog Connector.
Discovers and ingests company, provider, and public procurement datasets using the CKAN API.
"""

from typing import List, Dict, Any, Optional
from .base import SourceConnector
from ..models.company import CanonicalCompany, Address
from ..models.source_record import RawSourcePayload, SourceProvenanceRecord
from ..pipeline.normalization import normalize_company_name, normalize_website
from ..utils.rfc_utils import clean_rfc, is_valid_rfc, get_rfc_type
from ..utils.hashing import sha256_dict, generate_entity_fingerprint, generate_company_id
from ..utils.logging import logger


class DatosGobConnector(SourceConnector):
    """Catalog discovery connector for Mexico's National Open Data Portal (datos.gob.mx)."""

    def fetch(self, limit: Optional[int] = None) -> List[RawSourcePayload]:
        raw_payloads: List[RawSourcePayload] = []
        target_limit = limit or 100
        base_url = self.config.base_url or "https://datos.gob.mx/busca/api/3/action"

        try:
            # CKAN package search for business datasets
            search_url = f"{base_url}/package_search"
            params = {"q": "empresas OR proveedores", "rows": min(target_limit, 20)}
            logger.info("Discovering open datasets on datos.gob.mx", params=params)
            response = self.http_client.get(search_url, params=params)
            data = response.json()
            results = data.get("result", {}).get("results", [])

            for pkg in results:
                raw_payloads.append(
                    RawSourcePayload(
                        source="DATOS_GOB",
                        source_record_id=pkg.get("id", ""),
                        source_url=f"https://datos.gob.mx/dataset/{pkg.get('name', '')}",
                        raw_data=pkg,
                        raw_hash=sha256_dict(pkg),
                    )
                )
                if len(raw_payloads) >= target_limit:
                    break
        except Exception as e:
            logger.warn(f"datos.gob.mx catalog query notice: {str(e)}")

        return raw_payloads

    def parse(self, payload: RawSourcePayload) -> Dict[str, Any]:
        d = payload.raw_data
        return {
            "dataset_id": d.get("id"),
            "title": d.get("title"),
            "organization": d.get("organization", {}).get("title") if isinstance(d.get("organization"), dict) else "",
            "notes": d.get("notes"),
        }

    def normalize(self, parsed: Dict[str, Any], provenance: SourceProvenanceRecord) -> CanonicalCompany:
        legal_orig, legal_norm = normalize_company_name(parsed.get("organization") or parsed.get("title"))
        fp = generate_entity_fingerprint(normalized_name=legal_norm)
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
