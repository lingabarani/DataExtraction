import requests
from us_b2b.config.settings import settings
import logging

logger = logging.getLogger(__name__)

class OpenFDAClient:
    BASE_URL = "https://api.fda.gov"

    def __init__(self):
        self.api_key = settings.OPENFDA_API_KEY
        self.session = requests.Session()

    def get_data(self, endpoint, params=None):
        if params is None:
            params = {}
            
        if self.api_key:
            params['api_key'] = self.api_key
            
        url = f"{self.BASE_URL}/{endpoint}"
        target_limit = params.pop('limit', 100)
        results = []
        skip = 0
        
        while len(results) < target_limit:
            fetch_limit = min(1000, target_limit - len(results))
            params['limit'] = fetch_limit
            params['skip'] = skip
            
            try:
                response = self.session.get(url, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
                items = data.get("results", [])
                if not items:
                    break
                results.extend(items)
                skip += len(items)
            except requests.RequestException as e:
                logger.error(f"OpenFDA API request failed: {e}")
                break
                
        return {"results": results}
