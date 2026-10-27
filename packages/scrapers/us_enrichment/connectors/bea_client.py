import requests
from us_b2b.config.settings import settings
import logging

logger = logging.getLogger(__name__)

class BEAClient:
    BASE_URL = "https://apps.bea.gov/api/data"

    def __init__(self):
        self.api_key = settings.BEA_DATA_API_KEY
        self.session = requests.Session()

    def get_data(self, dataset_name, params=None):
        if params is None:
            params = {}
            
        params['UserID'] = self.api_key
        params['method'] = 'GetData'
        params['datasetname'] = dataset_name
        params['ResultFormat'] = 'json'
            
        try:
            response = self.session.get(self.BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"BEA API request failed: {e}")
            return None
