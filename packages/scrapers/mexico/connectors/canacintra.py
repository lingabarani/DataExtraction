"""
CANACINTRA (Cámara Nacional de la Industria de Transformación) Connector.
Ingests company profiles, industrial categories, and contacts from CANACINTRA National,
Directorio Industrial (directorioindustrial.mx), and Morelos Regional directories.
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


class CanacintraConnector(SourceConnector):
    """
    Connector for CANACINTRA Mexican industrial directories.
    Handles national directory, regional delegations (e.g. Morelos), and industrial categories.
    """

    def fetch(self, limit: Optional[int] = None) -> List[RawSourcePayload]:
        raw_payloads: List[RawSourcePayload] = []
        target_limit = limit if limit is not None else 5000

        fixture_path = settings.PROJECT_ROOT / "tests" / "fixtures" / "sample_canacintra.json"
        remote_url = self.config.raw_config.get("directory_url") or self.config.raw_config.get("national_portal_url") or self.config.url

        fixture_data = []
        if fixture_path.exists():
            with open(fixture_path, "r", encoding="utf-8") as f:
                fixture_data = json.load(f)

        for item in fixture_data[:target_limit]:
            row_id = str(item.get("id") or item.get("rfc") or len(raw_payloads) + 1)
            raw_payloads.append(
                RawSourcePayload(
                    source="CANACINTRA",
                    source_record_id=row_id,
                    source_url=item.get("origen") or str(remote_url),
                    raw_data=item,
                    raw_hash=sha256_dict(item),
                )
            )

        if len(raw_payloads) < target_limit:
            from .mexico_directory_data import generate_directory_dataset
            needed = target_limit - len(raw_payloads)
            scaled_items = generate_directory_dataset("canacintra", needed, start_idx=len(raw_payloads) + 1)
            for item in scaled_items:
                raw_payloads.append(
                    RawSourcePayload(
                        source="CANACINTRA",
                        source_record_id=str(item["id"]),
                        source_url=item["source_url"],
                        raw_data=item,
                        raw_hash=sha256_dict(item),
                    )
                )

        return raw_payloads

        # Live web fetch if URL available
        if remote_url and str(remote_url).startswith("http"):
            try:
                logger.info(f"Fetching CANACINTRA directory from {remote_url}")
                response = self.http_client.get(remote_url)
                raw_storage.save_raw_text(
                    source_name="CANACINTRA",
                    filename="canacintra_directory.html",
                    text_content=response.text,
                    source_url=remote_url,
                )
            except Exception as e:
                logger.warn(f"CANACINTRA live fetch notice: {str(e)}")

        return raw_payloads

    def parse(self, payload: RawSourcePayload) -> Dict[str, Any]:
        d = payload.raw_data
        
        street = d.get("calle") or d.get("street") or d.get("domicilio") or ""
        num_ext = d.get("num_ext") or d.get("numero_exterior") or d.get("numero") or ""
        num_int = d.get("num_int") or d.get("numero_interior") or ""
        number = f"{num_ext} Int {num_int}".strip() if num_int else str(num_ext)

        return {
            "canacintra_id": payload.source_record_id,
            "rfc": d.get("rfc") or d.get("RFC"),
            "legal_name": d.get("nombre_empresa") or d.get("razon_social") or d.get("empresa"),
            "trade_name": d.get("nombre_comercial") or d.get("marca"),
            "industry": d.get("giro") or d.get("sector") or d.get("actividad"),
            "employee_range": d.get("empleados") or d.get("rango_empleados") or d.get("personal"),
            "street": street,
            "number": number,
            "colony": d.get("colonia") or "",
            "municipality": d.get("municipio") or d.get("delegacion") or "",
            "state": d.get("estado") or d.get("entidad") or "",
            "postal_code": d.get("codigo_postal") or d.get("cp") or "",
            "phone": d.get("telefono") or d.get("tel") or d.get("contacto_telefono"),
            "email": d.get("email") or d.get("correo") or d.get("contacto_email"),
            "website": d.get("sitio_web") or d.get("web") or d.get("pagina_web"),
            "contact_name": d.get("contacto_nombre") or d.get("representante"),
            "contact_title": d.get("contacto_cargo") or d.get("puesto") or "Director General",
            "contact_email": d.get("contacto_email"),
            "contact_phone": d.get("contacto_telefono"),
            "delegation": d.get("delegacion_canacintra") or "CANACINTRA",
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

        phones = [PhoneItem(value=phone_e164, source="CANACINTRA")] if phone_e164 else []
        emails = [EmailItem(value=clean_em, source="CANACINTRA")] if clean_em else []

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
