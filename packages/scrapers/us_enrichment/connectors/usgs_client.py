import requests
from us_b2b.config.settings import settings
import logging

logger = logging.getLogger(__name__)

class USGSClient:
    BASE_URL = "https://waterservices.usgs.gov/nwis"

    def __init__(self):
        # USGS generally uses open endpoints, but we can pass keys if required by specific endpoints
        self.api_key = settings.USGS_WATER_API_KEY
        self.session = requests.Session()

    def get_data(self, endpoint, params=None):
        if params is None:
            params = {}
            
        params['format'] = 'json'
            
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"USGS API request failed: {e}")
            return None
