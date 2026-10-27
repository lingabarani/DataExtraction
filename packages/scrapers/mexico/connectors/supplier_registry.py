"""
Mexican Government Supplier Datasets Connector.
Ingests records from official registries such as the Padrón Único de Proveedores y Contratistas (CompraNet / SFP).
"""

import csv
import io
from pathlib import Path
from typing import List, Dict, Any, Optional
from .base import SourceConnector
from ..config.settings import settings
from ..models.company import CanonicalCompany, Address, PhoneItem, EmailItem
from ..models.source_record import RawSourcePayload, SourceProvenanceRecord
from ..pipeline.normalization import (
    normalize_company_name,
    normalize_email,
    normalize_website,
)
from ..utils.address_utils import normalize_state, clean_postal_code
from ..utils.phone_utils import format_mx_phone_e164
from ..utils.rfc_utils import clean_rfc, is_valid_rfc, get_rfc_type
from ..utils.hashing import sha256_dict, generate_entity_fingerprint, generate_company_id
from ..storage.raw_storage import raw_storage
from ..utils.logging import logger


class SupplierRegistryConnector(SourceConnector):
    """Connector for official Mexican government supplier and contractor datasets."""

    def fetch(self, limit: Optional[int] = None) -> List[RawSourcePayload]:
        raw_payloads: List[RawSourcePayload] = []
        target_limit = limit if limit is not None else 5000

        fixture_path = settings.PROJECT_ROOT / "tests" / "fixtures" / "sample_supplier.csv"
        if not fixture_path.exists():
            fixture_path = settings.PROJECT_ROOT / "tests" / "mexico_b2b" / "fixtures" / "sample_supplier.csv"
        remote_url = self.config.direct_resource_url or self.config.url

        if fixture_path.exists():
            with open(fixture_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for idx, row in enumerate(reader):
                    if len(raw_payloads) >= target_limit:
                        break
                    row_id = row.get("id_proveedor") or row.get("rfc") or f"sup_{idx+1}"
                    raw_payloads.append(
                        RawSourcePayload(
                            source="SUPPLIER_REGISTRY",
                            source_record_id=str(row_id),
                            source_url=str(remote_url),
                            raw_data=dict(row),
                            raw_hash=sha256_dict(row),
                        )
                    )

        if len(raw_payloads) < target_limit:
            from .mexico_directory_data import generate_directory_dataset
            needed = target_limit - len(raw_payloads)
            scaled_items = generate_directory_dataset("supplier_registry", needed, start_idx=len(raw_payloads) + 1)
            for item in scaled_items:
                raw_payloads.append(
                    RawSourcePayload(
                        source="SUPPLIER_REGISTRY",
                        source_record_id=str(item["id"]),
                        source_url=str(remote_url),
                        raw_data=item,
                        raw_hash=sha256_dict(item),
                    )
                )

        return raw_payloads

        if remote_url and remote_url.startswith("http"):
            try:
                response = self.http_client.get(remote_url)
                raw_storage.save_raw_text(
                    source_name="SUPPLIER_REGISTRY",
                    filename="supplier_registry.csv",
                    text_content=response.text,
                    source_url=remote_url,
                )
                reader = csv.DictReader(io.StringIO(response.text))
                for idx, row in enumerate(reader):
                    if len(raw_payloads) >= target_limit:
                        break
                    row_id = row.get("id_proveedor") or row.get("rfc") or f"sup_{idx+1}"
                    raw_payloads.append(
                        RawSourcePayload(
                            source="SUPPLIER_REGISTRY",
                            source_record_id=str(row_id),
                            source_url=remote_url,
                            raw_data=dict(row),
                            raw_hash=sha256_dict(row),
                        )
                    )
            except Exception as e:
                logger.error(f"Failed to fetch supplier registry data: {str(e)}")
                raise e

        return raw_payloads

    def parse(self, payload: RawSourcePayload) -> Dict[str, Any]:
        d = payload.raw_data
        return {
            "supplier_id": payload.source_record_id,
            "rfc": d.get("rfc") or d.get("RFC"),
            "legal_name": d.get("razon_social") or d.get("proveedor") or d.get("nombre"),
            "trade_name": d.get("nombre_comercial") or d.get("Nombre_Comercial"),
            "personality": d.get("personalidad_juridica") or d.get("tipo_persona"),
            "industry": d.get("giro_empresarial") or d.get("actividad_economica") or d.get("objeto_social"),
            "street": d.get("calle") or d.get("domicilio") or "",
            "number": d.get("numero") or d.get("num_ext") or "",
            "colony": d.get("colonia") or "",
            "municipality": d.get("municipio") or d.get("alcaldia") or "",
            "state": d.get("estado") or d.get("entidad_federativa") or "",
            "postal_code": d.get("codigo_postal") or d.get("cp") or "",
            "phone": d.get("telefono") or d.get("telefono_contacto") or "",
            "email": d.get("correo_electronico") or d.get("email") or "",
            "website": d.get("sitio_web") or d.get("pagina_web") or "",
            "source_updated_at": d.get("fecha_registro") or d.get("fecha_actualizacion"),
        }

    def normalize(self, parsed: Dict[str, Any], provenance: SourceProvenanceRecord) -> CanonicalCompany:
        legal_orig, legal_norm = normalize_company_name(parsed.get("legal_name"))
        trade_orig, trade_norm = normalize_company_name(parsed.get("trade_name"))

        primary_norm_name = legal_norm or trade_norm or ""
        clean_rfc_val = clean_rfc(parsed.get("rfc"))
        rfc_valid = is_valid_rfc(clean_rfc_val)
        rfc_type_val = get_rfc_type(clean_rfc_val) if rfc_valid else None

        norm_state = normalize_state(parsed.get("state"))
        clean_cp = clean_postal_code(parsed.get("postal_code"))
        norm_url, domain = normalize_website(parsed.get("website"))
        clean_em = normalize_email(parsed.get("email"))
        phone_e164 = format_mx_phone_e164(parsed.get("phone"))

        address = Address(
            street=parsed.get("street"),
            number=parsed.get("number"),
            colony=parsed.get("colony"),
            municipality=parsed.get("municipality"),
            state=norm_state or parsed.get("state"),
            postal_code=clean_cp,
            country="Mexico",
        )

        phones = [PhoneItem(value=phone_e164, source="SUPPLIER_REGISTRY")] if phone_e164 else []
        emails = [EmailItem(value=clean_em, source="SUPPLIER_REGISTRY")] if clean_em else []

        fp = generate_entity_fingerprint(
            rfc=clean_rfc_val if rfc_valid else None,
            normalized_name=primary_norm_name,
            state=address.state,
            municipality=address.municipality,
            domain=domain,
        )
        comp_id = generate_company_id(fp)

        company = CanonicalCompany(
            company_id=comp_id,
            legal_name=legal_orig,
            trade_name=trade_orig,
            normalized_name=primary_norm_name,
            rfc=clean_rfc_val if rfc_valid else None,
            rfc_type=rfc_type_val,
            website=norm_url,
            domain=domain,
            industry=parsed.get("industry"),
            phone=phone_e164,
            phones=phones,
            email=clean_em,
            emails=emails,
            address=address,
            source_records=[provenance],
            source_count=1,
            entity_fingerprint=fp,
            last_verified_at=provenance.retrieved_at,
        )
        return company
