"""
INEGI DENUE (Directorio Estadístico Nacional de Unidades Económicas) Connector.
Supports official INEGI REST API v1.0, downloadable bulk files (CSV/ZIP), and local bulk feeds.
"""

import os
import re
import csv
import json
import zipfile
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
from ..utils.phone_utils import format_mx_phone_e164, is_valid_mx_phone
from ..utils.rfc_utils import clean_rfc, is_valid_rfc, get_rfc_type
from ..utils.hashing import sha256_dict, generate_entity_fingerprint, generate_company_id
from ..storage.raw_storage import raw_storage
from ..utils.logging import logger


class DenueConnector(SourceConnector):
    """
    Connector for INEGI DENUE official API, bulk open-data downloads, and local data drops.
    """

    def __init__(self, config):
        super().__init__(config)
        self.api_token = settings.DENUE_API_TOKEN or os.getenv(self.config.token_env or "DENUE_API_TOKEN")

    def _get_api_token_or_fail(self) -> str:
        token = self.api_token
        if not token or token.strip() == "":
            raise ValueError(
                "DENUE_API_TOKEN is not configured. "
                "Please register at https://www.inegi.org.mx/servicios/api_denue.html "
                "and set DENUE_API_TOKEN in your .env file or environment variables."
            )
        return token.strip()

    def fetch(self, limit: Optional[int] = None) -> List[RawSourcePayload]:
        """
        Fetches records via bulk raw files in data/raw/ or official DENUE REST API.
        If no bulk file and API fails, falls back to local sample fixture.
        """
        raw_payloads: List[RawSourcePayload] = []
        target_limit = limit if limit is not None else 10_000_000

        # 1. Check for raw bulk CSV files in data/raw/denue/ or data/raw/
        raw_denue_dir = settings.RAW_DATA_DIR / "denue"
        raw_candidates = []
        if raw_denue_dir.exists():
            raw_candidates.extend(list(raw_denue_dir.glob("*.csv")))
        raw_candidates.extend(list(settings.RAW_DATA_DIR.glob("*denue*.csv")))
        raw_candidates.extend(list(settings.RAW_DATA_DIR.glob("*bulk*.csv")))

        # Sort by file size descending so the full dataset (e.g. 13.6MB 30k+ records) is read first
        raw_candidates = sorted(list(set(raw_candidates)), key=lambda p: p.stat().st_size, reverse=True)

        if raw_candidates:
            for bulk_csv_path in raw_candidates:
                if len(raw_payloads) >= target_limit:
                    break
                logger.info(f"Streaming DENUE records from bulk file: {bulk_csv_path.name}", limit=target_limit, current_count=len(raw_payloads))
                with open(bulk_csv_path, "r", encoding="utf-8-sig", errors="ignore") as f:
                    reader = csv.DictReader(f)
                    for idx, row in enumerate(reader):
                        if len(raw_payloads) >= target_limit:
                            break
                        row_id = str(row.get("clee") or row.get("id") or row.get("Id") or f"denue_{idx+1}")
                        raw_payloads.append(
                            RawSourcePayload(
                                source="DENUE",
                                source_record_id=row_id,
                                source_url=f"file://{bulk_csv_path.name}",
                                raw_data=dict(row),
                                raw_hash=sha256_dict(row),
                            )
                        )
            return raw_payloads

        # 2. Check if local test fixture exists and limit is small (e.g. unit tests)
        fixture_path = settings.PROJECT_ROOT / "tests" / "fixtures" / "sample_denue.json"
        if not fixture_path.exists():
            fixture_path = settings.PROJECT_ROOT / "tests" / "mexico_b2b" / "fixtures" / "sample_denue.json"

        # 3. Attempt API Query if token is configured
        try:
            token = self._get_api_token_or_fail()
            batch_size = min(target_limit, 50)
            reg_start = 1
            base_url = self.config.base_url or "https://www.inegi.org.mx/app/api/denue/v1/consulta"
            endpoint = self.config.endpoints.get("search_area_act", "BuscarAreaAct")
            condition = self.config.raw_config.get("default_condition", "todos")
            state_code = self.config.raw_config.get("default_state_code", "09")
            act_code = self.config.raw_config.get("default_activity_code", "0")

            while len(raw_payloads) < target_limit:
                reg_end = min(reg_start + batch_size - 1, target_limit)
                url = f"{base_url}/{endpoint}/{condition}/{state_code}/0/{act_code}/{reg_start}/{reg_end}/{token}"
                
                logger.info("Querying INEGI DENUE API", start=reg_start, end=reg_end)
                response = self.http_client.get(url)
                data = response.json()

                if not data or not isinstance(data, list):
                    break

                raw_storage.save_raw_text(
                    source_name="DENUE",
                    filename=f"denue_api_{state_code}_{reg_start}_{reg_end}.json",
                    text_content=response.text,
                    source_url=self.http_client._sanitize_url(url),
                )

                for item in data:
                    item_id = str(item.get("CLEE") or item.get("Id") or item.get("id") or len(raw_payloads) + 1)
                    raw_hash = sha256_dict(item)
                    raw_payloads.append(
                        RawSourcePayload(
                            source="DENUE",
                            source_record_id=item_id,
                            source_url=base_url,
                            raw_data=item,
                            raw_hash=raw_hash,
                        )
                    )
                    if len(raw_payloads) >= target_limit:
                        break

                if len(data) < batch_size:
                    break

                reg_start += batch_size

        except (ValueError, Exception) as e:
            if fixture_path.exists():
                logger.warn(f"INEGI DENUE API notice ({type(e).__name__}); falling back to sample fixture from {fixture_path.name}")
                with open(fixture_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data[:target_limit]:
                    item_id = str(item.get("CLEE") or item.get("Id") or len(raw_payloads) + 1)
                    raw_payloads.append(
                        RawSourcePayload(
                            source="DENUE",
                            source_record_id=item_id,
                            source_url="local_fixture://denue",
                            raw_data=item,
                            raw_hash=sha256_dict(item),
                        )
                    )
            else:
                raise e

        return raw_payloads

    def parse(self, payload: RawSourcePayload) -> Dict[str, Any]:
        """Extracts standard dictionary fields from DENUE raw item (handles both API and bulk CSV schemas)."""
        d = payload.raw_data
        
        # Address construction
        street_type = d.get("Tipo_vialidad") or d.get("tipo_vialidad") or d.get("tipo_vial") or ""
        street_name = d.get("Calle") or d.get("calle") or d.get("Nombre_vialidad") or d.get("nom_vial") or ""
        street = f"{street_type} {street_name}".strip() if street_type else street_name
        num_ext = d.get("Num_Exterior") or d.get("num_Exterior") or d.get("Numero_exterior") or d.get("numero_ext") or ""
        num_int = d.get("Num_Interior") or d.get("num_Interior") or d.get("Letra_interior") or d.get("numero_int") or ""
        full_num = f"{num_ext} Int {num_int}".strip() if num_int else str(num_ext)

        # State & Municipality
        location_raw = d.get("Ubicacion") or d.get("ubicacion") or ""
        muni = d.get("Municipio") or d.get("municipio") or ""
        state = d.get("Entidad") or d.get("entidad") or d.get("Estado") or ""
        
        if not state and "," in location_raw:
            parts = location_raw.split(",")
            muni = parts[0].strip()
            state = parts[-1].strip()

        # Coordinates
        lat = d.get("Latitud") or d.get("latitud")
        lng = d.get("Longitud") or d.get("longitud")
        lat_f = float(lat) if lat is not None and str(lat).strip() != "" else None
        lng_f = float(lng) if lng is not None and str(lng).strip() != "" else None

        return {
            "clee": d.get("CLEE") or d.get("clee"),
            "establishment_id": d.get("Id") or d.get("id"),
            "trade_name": d.get("Nombre") or d.get("nombre") or d.get("nom_estab"),
            "legal_name": d.get("Razon_social") or d.get("razon_social") or d.get("raz_soc"),
            "rfc": d.get("rfc") or d.get("RFC"),
            "industry": d.get("Clase_actividad") or d.get("clase_actividad") or d.get("Nombre_act") or d.get("nombre_act"),
            "industry_code": d.get("Codigo_act") or d.get("codigo_act"),
            "employee_range": d.get("Estrato") or d.get("estrato") or d.get("Personal_ocupado") or d.get("per_ocu"),
            "street": street,
            "number": full_num,
            "colony": d.get("Colonia") or d.get("colonia") or d.get("Nombre_asentamiento") or d.get("nomb_asent"),
            "municipality": muni,
            "state": state,
            "postal_code": d.get("CP") or d.get("cp") or d.get("Codigo_postal") or d.get("cod_postal"),
            "phone": d.get("Telefono") or d.get("telefono") or d.get("tel"),
            "email": d.get("Correo_e") or d.get("correo_e") or d.get("Correo_electronico") or d.get("correoelec"),
            "website": d.get("Sitio_internet") or d.get("sitio_internet") or d.get("Pagina_web") or d.get("sitio_web"),
            "latitude": lat_f,
            "longitude": lng_f,
            "source_updated_at": d.get("Fecha_alta") or d.get("fecha_alta"),
            "representante_legal": d.get("representante_legal"),
            "cargo_representante": d.get("cargo_representante"),
            "correo_directo": d.get("correo_directo"),
            "telefono_directo": d.get("telefono_directo"),
        }

    def normalize(self, parsed: Dict[str, Any], provenance: SourceProvenanceRecord) -> CanonicalCompany:
        """Transforms parsed DENUE data into CanonicalCompany."""
        trade_orig, trade_norm = normalize_company_name(parsed.get("trade_name"))
        legal_orig, legal_norm = normalize_company_name(parsed.get("legal_name"))

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

        phones = [PhoneItem(value=phone_e164, source="DENUE")] if phone_e164 else []
        emails = [EmailItem(value=clean_em, source="DENUE")] if clean_em else []

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
            industry_code=parsed.get("industry_code"),
            employee_count_min=emp_min,
            employee_count_max=emp_max,
            employee_count_source=emp_src,
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
