import requests
from us_b2b.config.settings import settings
import logging

logger = logging.getLogger(__name__)

class BLSClient:
    BASE_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

    def __init__(self):
        self.api_key = settings.BLS_API_KEY
        self.session = requests.Session()

    def get_data(self, series_ids, start_year, end_year):
        payload = {
            "seriesid": series_ids,
            "startyear": str(start_year),
            "endyear": str(end_year)
        }
        if self.api_key:
            payload['registrationkey'] = self.api_key
            
        try:
            response = self.session.post(self.BASE_URL, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"BLS API request failed: {e}")
            return None
