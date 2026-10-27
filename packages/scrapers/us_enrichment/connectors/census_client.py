import requests
from us_b2b.config.settings import settings
import logging

logger = logging.getLogger(__name__)

class CensusClient:
    BASE_URL = "https://api.census.gov/data"

    def __init__(self):
        self.api_key = settings.CENSUS_DATA_API_KEY
        self.session = requests.Session()

    def get_data(self, endpoint, params=None):
        if params is None:
            params = {}
        if self.api_key:
            params['key'] = self.api_key
            
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Census API request failed: {e}")
            return None
