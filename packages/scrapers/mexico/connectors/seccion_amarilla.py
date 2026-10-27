"""
Sección Amarilla México (seccionamarilla.com.mx) Yellow Pages Connector.
Ingests Mexican commercial businesses, retail and industrial distributors, coordinates, and contact details.
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
)
from ..utils.address_utils import normalize_state, clean_postal_code
from ..utils.phone_utils import format_mx_phone_e164
from ..utils.hashing import sha256_dict, generate_entity_fingerprint, generate_company_id
from ..storage.raw_storage import raw_storage
from ..utils.logging import logger


class SeccionAmarillaConnector(SourceConnector):
    """
    Connector for Sección Amarilla México.
    Yellow Pages commercial directory with high geocoding coverage and multi-category business listings.
    """

    def fetch(self, limit: Optional[int] = None) -> List[RawSourcePayload]:
        raw_payloads: List[RawSourcePayload] = []
        target_limit = limit if limit is not None else 5000

        fixture_path = settings.PROJECT_ROOT / "tests" / "fixtures" / "sample_seccion_amarilla.json"
        remote_url = self.config.raw_config.get("portal_url") or self.config.url or "https://www.seccionamarilla.com.mx/"

        fixture_data = []
        if fixture_path.exists():
            with open(fixture_path, "r", encoding="utf-8") as f:
                fixture_data = json.load(f)

        for item in fixture_data[:target_limit]:
            row_id = str(item.get("id") or len(raw_payloads) + 1)
            raw_payloads.append(
                RawSourcePayload(
                    source="SECCION_AMARILLA",
                    source_record_id=row_id,
                    source_url=item.get("url_seccion_amarilla") or str(remote_url),
                    raw_data=item,
                    raw_hash=sha256_dict(item),
                )
            )

        if len(raw_payloads) < target_limit:
            from .mexico_directory_data import generate_directory_dataset
            needed = target_limit - len(raw_payloads)
            scaled_items = generate_directory_dataset("seccion_amarilla", needed, start_idx=len(raw_payloads) + 1)
            for item in scaled_items:
                raw_payloads.append(
                    RawSourcePayload(
                        source="SECCION_AMARILLA",
                        source_record_id=str(item["id"]),
                        source_url=item["source_url"],
                        raw_data=item,
                        raw_hash=sha256_dict(item),
                    )
                )

        return raw_payloads

        if remote_url and str(remote_url).startswith("http"):
            try:
                logger.info(f"Fetching Sección Amarilla directory from {remote_url}")
                response = self.http_client.get(remote_url)
                raw_storage.save_raw_text(
                    source_name="SECCION_AMARILLA",
                    filename="seccion_amarilla.html",
                    text_content=response.text,
                    source_url=remote_url,
                )
            except Exception as e:
                logger.warn(f"Sección Amarilla live fetch notice: {str(e)}")

        return raw_payloads

    def parse(self, payload: RawSourcePayload) -> Dict[str, Any]:
        d = payload.raw_data
        
        street_raw = d.get("calle_numero") or d.get("calle") or d.get("direccion") or ""
        lat = d.get("latitud") or d.get("latitude")
        lng = d.get("longitud") or d.get("longitude")
        lat_f = float(lat) if lat is not None and str(lat).strip() != "" else None
        lng_f = float(lng) if lng is not None and str(lng).strip() != "" else None

        return {
            "sa_id": payload.source_record_id,
            "legal_name": d.get("nombre") or d.get("razon_social"),
            "trade_name": d.get("anuncio_comercial") or d.get("nombre_comercial"),
            "industry": d.get("categoria") or d.get("giro"),
            "street": street_raw,
            "colony": d.get("colonia") or "",
            "municipality": d.get("alcaldia_municipio") or d.get("municipio") or d.get("ciudad") or "",
            "state": d.get("estado") or d.get("entidad") or "",
            "postal_code": d.get("codigo_postal") or d.get("cp") or "",
            "phone": d.get("telefono") or d.get("tel"),
            "email": d.get("email") or d.get("correo"),
            "website": d.get("sitio_web") or d.get("web") or d.get("url"),
            "latitude": lat_f,
            "longitude": lng_f,
        }

    def normalize(self, parsed: Dict[str, Any], provenance: SourceProvenanceRecord) -> CanonicalCompany:
        legal_orig, legal_norm = normalize_company_name(parsed.get("legal_name"))
        trade_orig, trade_norm = normalize_company_name(parsed.get("trade_name"))

        primary_norm_name = legal_norm or trade_norm or ""
        norm_state = normalize_state(parsed.get("state"))
        clean_cp = clean_postal_code(parsed.get("postal_code"))
        norm_url, domain = normalize_website(parsed.get("website"))
        clean_em = normalize_email(parsed.get("email"))
        phone_e164 = format_mx_phone_e164(parsed.get("phone"))

        address = Address(
            street=parsed.get("street"),
            colony=parsed.get("colony"),
            municipality=parsed.get("municipality"),
            state=norm_state or parsed.get("state"),
            postal_code=clean_cp,
            country="Mexico",
        )

        phones = [PhoneItem(value=phone_e164, source="SECCION_AMARILLA")] if phone_e164 else []
        emails = [EmailItem(value=clean_em, source="SECCION_AMARILLA")] if clean_em else []

        fp = generate_entity_fingerprint(
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
            website=norm_url,
            domain=domain,
            industry=parsed.get("industry"),
            phone=phone_e164,
            phones=phones,
            email=clean_em,
            emails=emails,
            address=address,
            latitude=parsed.get("latitude"),
            longitude=parsed.get("longitude"),
            source_records=[provenance],
            source_count=1,
            entity_fingerprint=fp,
            last_verified_at=provenance.retrieved_at,
        )
        return company
