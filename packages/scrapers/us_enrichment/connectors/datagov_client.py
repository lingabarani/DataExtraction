import requests
from us_b2b.config.settings import settings
import logging

logger = logging.getLogger(__name__)

class DataGovClient:
    BASE_URL = "https://api.data.gov/ed/collegescorecard/v1" # Reliable standard endpoint

    def __init__(self):
        self.api_key = settings.DATA_GOV_API_KEY
        self.session = requests.Session()

    def get_data(self, endpoint, params=None):
        if params is None:
            params = {}
            
        if self.api_key:
            params['api_key'] = self.api_key
            
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Data.gov API request failed: {e}")
            return None
