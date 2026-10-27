from dataclasses import dataclass
from typing import Optional, List

@dataclass
class USCompany:
    company_id: str
    legal_name: str
    ein: Optional[str] = None
    naics_code: Optional[str] = None
    industry_description: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None  # 2-letter abbreviation
    zip_code: Optional[str] = None
    sources: List[str] = None
    data_quality_score: float = 0.0

    def __post_init__(self):
        if self.sources is None:
            self.sources = []
