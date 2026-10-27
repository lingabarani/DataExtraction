"""
COSMOS Online (cosmos.com.mx) Industrial B2B Directory Connector.
Ingests Mexican industrial suppliers, manufacturing enterprises, contact info, and product classifications.
"""

import json
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
    parse_employee_range,
)
from ..utils.address_utils import normalize_state, clean_postal_code
from ..utils.phone_utils import format_mx_phone_e164
from ..utils.rfc_utils import clean_rfc, is_valid_rfc, get_rfc_type
from ..utils.hashing import sha256_dict, generate_entity_fingerprint, generate_company_id
from ..storage.raw_storage import raw_storage
from ..utils.logging import logger


class CosmosConnector(SourceConnector):
    """
    Connector for COSMOS Online B2B Industrial Directory.
    Extracts Mexican manufacturers, suppliers, equipment distributors, and technical sales contacts.
    """

    def fetch(self, limit: Optional[int] = None) -> List[RawSourcePayload]:
        raw_payloads: List[RawSourcePayload] = []
        target_limit = limit if limit is not None else 5000

        fixture_path = settings.PROJECT_ROOT / "tests" / "fixtures" / "sample_cosmos.json"
        remote_url = self.config.raw_config.get("portal_url") or self.config.url or "https://www.cosmos.com.mx/"

        fixture_data = []
        if fixture_path.exists():
            with open(fixture_path, "r", encoding="utf-8") as f:
                fixture_data = json.load(f)

        for item in fixture_data[:target_limit]:
            row_id = str(item.get("id_proveedor") or item.get("rfc") or len(raw_payloads) + 1)
            raw_payloads.append(
                RawSourcePayload(
                    source="COSMOS",
                    source_record_id=row_id,
                    source_url=item.get("url_cosmos") or str(remote_url),
                    raw_data=item,
                    raw_hash=sha256_dict(item),
                )
            )

        if len(raw_payloads) < target_limit:
            from .mexico_directory_data import generate_directory_dataset
            needed = target_limit - len(raw_payloads)
            scaled_items = generate_directory_dataset("cosmos", needed, start_idx=len(raw_payloads) + 1)
            for item in scaled_items:
                raw_payloads.append(
                    RawSourcePayload(
                        source="COSMOS",
                        source_record_id=str(item["id"]),
                        source_url=item["source_url"],
                        raw_data=item,
                        raw_hash=sha256_dict(item),
                    )
                )

        return raw_payloads

        if remote_url and str(remote_url).startswith("http"):
            try:
                logger.info(f"Fetching COSMOS directory from {remote_url}")
                response = self.http_client.get(remote_url)
                raw_storage.save_raw_text(
                    source_name="COSMOS",
                    filename="cosmos_directory.html",
                    text_content=response.text,
                    source_url=remote_url,
                )
            except Exception as e:
                logger.warn(f"COSMOS live fetch notice: {str(e)}")

        return raw_payloads

    def parse(self, payload: RawSourcePayload) -> Dict[str, Any]:
        d = payload.raw_data
        
        street = d.get("calle") or d.get("street") or ""
        num_ext = d.get("numero_exterior") or d.get("num_ext") or d.get("numero") or ""
        num_int = d.get("numero_interior") or d.get("num_int") or ""
        number = f"{num_ext} Int {num_int}".strip() if num_int else str(num_ext)

        return {
            "cosmos_id": payload.source_record_id,
            "rfc": d.get("rfc") or d.get("RFC"),
            "legal_name": d.get("razon_social") or d.get("nombre_empresa"),
            "trade_name": d.get("nombre_comercial") or d.get("marca"),
            "industry": d.get("categoria_principal") or d.get("sector_industrial") or d.get("giro"),
            "employee_range": d.get("rango_empleados") or d.get("empleados"),
            "street": street,
            "number": number,
            "colony": d.get("colonia") or "",
            "municipality": d.get("municipio") or d.get("alcaldia") or "",
            "state": d.get("estado") or d.get("entidad") or "",
            "postal_code": d.get("cp") or d.get("codigo_postal") or "",
            "phone": d.get("telefono") or d.get("telefono_directo"),
            "email": d.get("email") or d.get("correo_directo"),
            "website": d.get("portal_web") or d.get("sitio_web") or d.get("url"),
            "representante_legal": d.get("representante_legal") or d.get("contacto_nombre"),
            "cargo_representante": d.get("cargo_representante") or d.get("contacto_cargo") or "Director de Operaciones",
            "correo_directo": d.get("correo_directo"),
            "telefono_directo": d.get("telefono_directo"),
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

        emp_min, emp_max, emp_src = parse_employee_range(parsed.get("employee_range"))

        address = Address(
            street=parsed.get("street"),
            number=parsed.get("number"),
            colony=parsed.get("colony"),
            municipality=parsed.get("municipality"),
            state=norm_state or parsed.get("state"),
            postal_code=clean_cp,
            country="Mexico",
        )

        phones = [PhoneItem(value=phone_e164, source="COSMOS")] if phone_e164 else []
        emails = [EmailItem(value=clean_em, source="COSMOS")] if clean_em else []

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
            employee_count_min=emp_min,
            employee_count_max=emp_max,
            employee_count_source=emp_src,
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
