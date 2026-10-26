"""
Taxonomy and Geographic Metadata for US OpenStreetMap Extraction Engine.
Defines 50 US states, geographical bounding boxes, and the 13 POI business category fields.
"""

from typing import Any, Dict, List, Optional, Tuple


US_STATES: List[Tuple[str, str]] = [
    ("Alabama", "AL"),
    ("Alaska", "AK"),
    ("Arizona", "AZ"),
    ("Arkansas", "AR"),
    ("California", "CA"),
    ("Colorado", "CO"),
    ("Connecticut", "CT"),
    ("Delaware", "DE"),
    ("Florida", "FL"),
    ("Georgia", "GA"),
    ("Hawaii", "HI"),
    ("Idaho", "ID"),
    ("Illinois", "IL"),
    ("Indiana", "IN"),
    ("Iowa", "IA"),
    ("Kansas", "KS"),
    ("Kentucky", "KY"),
    ("Louisiana", "LA"),
    ("Maine", "ME"),
    ("Maryland", "MD"),
    ("Massachusetts", "MA"),
    ("Michigan", "MI"),
    ("Minnesota", "MN"),
    ("Mississippi", "MS"),
    ("Missouri", "MO"),
    ("Montana", "MT"),
    ("Nebraska", "NE"),
    ("Nevada", "NV"),
    ("New Hampshire", "NH"),
    ("New Jersey", "NJ"),
    ("New Mexico", "NM"),
    ("New York", "NY"),
    ("North Carolina", "NC"),
    ("North Dakota", "ND"),
    ("Ohio", "OH"),
    ("Oklahoma", "OK"),
    ("Oregon", "OR"),
    ("Pennsylvania", "PA"),
    ("Rhode Island", "RI"),
    ("South Carolina", "SC"),
    ("South Dakota", "SD"),
    ("Tennessee", "TN"),
    ("Texas", "TX"),
    ("Utah", "UT"),
    ("Vermont", "VT"),
    ("Virginia", "VA"),
    ("Washington", "WA"),
    ("West Virginia", "WV"),
    ("Wisconsin", "WI"),
    ("Wyoming", "WY")
]

STATE_CODES: Dict[str, str] = dict(US_STATES)
CODE_TO_STATE: Dict[str, str] = {code: name for name, code in US_STATES}

# State Bounding Boxes: (min_lat, min_lon, max_lat, max_lon)
STATE_BOUNDING_BOXES: Dict[str, Tuple[float, float, float, float]] = {
    "Alabama": (30.14, -88.47, 35.01, -84.89),
    "Alaska": (51.20, -179.15, 71.39, -129.98),
    "Arizona": (31.33, -114.82, 37.00, -109.04),
    "Arkansas": (33.00, -94.62, 36.50, -89.64),
    "California": (32.53, -124.41, 42.01, -114.13),
    "Colorado": (36.99, -109.06, 41.00, -102.04),
    "Connecticut": (40.98, -73.73, 42.05, -71.79),
    "Delaware": (38.45, -75.79, 39.84, -75.05),
    "Florida": (24.52, -87.63, 31.00, -80.03),
    "Georgia": (30.36, -85.61, 35.00, -80.84),
    "Hawaii": (18.91, -160.25, 22.24, -154.81),
    "Idaho": (41.99, -117.24, 49.00, -111.04),
    "Illinois": (36.97, -91.51, 42.51, -87.50),
    "Indiana": (37.77, -88.10, 41.76, -84.78),
    "Iowa": (40.38, -96.64, 43.50, -90.14),
    "Kansas": (36.99, -102.05, 40.00, -94.59),
    "Kentucky": (36.50, -89.57, 39.15, -81.96),
    "Louisiana": (28.92, -94.04, 33.02, -88.82),
    "Maine": (43.06, -71.08, 47.46, -66.95),
    "Maryland": (37.91, -79.49, 39.72, -75.05),
    "Massachusetts": (41.24, -73.51, 42.89, -69.93),
    "Michigan": (41.70, -90.42, 48.31, -82.41),
    "Minnesota": (43.50, -97.24, 49.38, -89.49),
    "Mississippi": (30.17, -91.66, 35.00, -88.10),
    "Missouri": (35.99, -95.77, 40.61, -89.10),
    "Montana": (44.36, -116.05, 49.00, -104.04),
    "Nebraska": (40.00, -104.05, 43.00, -95.31),
    "Nevada": (35.00, -120.01, 42.00, -114.04),
    "New Hampshire": (42.70, -72.56, 45.31, -70.70),
    "New Jersey": (38.93, -75.56, 41.36, -73.89),
    "New Mexico": (31.33, -109.05, 37.00, -103.00),
    "New York": (40.50, -79.76, 45.02, -71.86),
    "North Carolina": (33.84, -84.32, 36.59, -75.46),
    "North Dakota": (45.93, -104.05, 49.00, -96.55),
    "Ohio": (38.40, -84.82, 41.98, -80.52),
    "Oklahoma": (33.62, -103.00, 37.00, -94.43),
    "Oregon": (41.99, -124.57, 46.29, -116.46),
    "Pennsylvania": (39.72, -80.52, 42.27, -74.69),
    "Rhode Island": (41.15, -71.86, 42.02, -71.12),
    "South Carolina": (32.03, -83.35, 35.22, -78.54),
    "South Dakota": (42.48, -104.06, 45.95, -96.44),
    "Tennessee": (34.98, -90.31, 36.68, -81.65),
    "Texas": (25.84, -106.65, 36.50, -93.51),
    "Utah": (36.99, -114.05, 42.00, -109.04),
    "Vermont": (42.73, -73.44, 45.02, -71.50),
    "Virginia": (36.54, -83.68, 39.47, -75.24),
    "Washington": (45.54, -124.76, 49.00, -116.92),
    "West Virginia": (37.20, -82.64, 40.64, -77.72),
    "Wisconsin": (42.49, -92.89, 47.08, -86.81),
    "Wyoming": (40.99, -111.06, 45.01, -104.05)
}

FIELDS_TAXONOMY: List[Dict[str, Any]] = [
    {
        "field": "shop",
        "category_group": "COMMERCIAL",
        "description": "Retail stores, supermarkets, boutiques, and specialty shops",
        "query_template": 'nwr["shop"]({s},{w},{n},{e});'
    },
    {
        "field": "office",
        "category_group": "COMMERCIAL",
        "description": "Corporate headquarters, law firms, consulting, and administrative offices",
        "query_template": 'nwr["office"]({s},{w},{n},{e});'
    },
    {
        "field": "amenity",
        "category_group": "SERVICES",
        "description": "General public facilities, civic amenities, and service locations",
        "query_template": 'nwr["amenity"]({s},{w},{n},{e});'
    },
    {
        "field": "craft",
        "category_group": "SERVICES",
        "description": "Artisans, tradespeople, contractors, and custom repair services",
        "query_template": 'nwr["craft"]({s},{w},{n},{e});'
    },
    {
        "field": "industrial",
        "category_group": "INDUSTRIAL",
        "description": "Manufacturing plants, distribution warehouses, and industrial parks",
        "query_template": (
            'nwr["industrial"]({s},{w},{n},{e});\n'
            '  nwr["landuse"="industrial"]({s},{w},{n},{e});\n'
            '  nwr["building"="industrial"]({s},{w},{n},{e});\n'
            '  nwr["building"="warehouse"]({s},{w},{n},{e});'
        )
    },
    {
        "field": "healthcare",
        "category_group": "HEALTHCARE",
        "description": "Hospitals, medical clinics, dental practices, pharmacies, and veterinary care",
        "query_template": (
            'nwr["healthcare"]({s},{w},{n},{e});\n'
            '  nwr["amenity"~"^(hospital|clinic|doctors|dentist|pharmacy|veterinary|nursing_home)$"]({s},{w},{n},{e});'
        )
    },
    {
        "field": "education",
        "category_group": "EDUCATION",
        "description": "Schools, colleges, universities, research centers, and training academies",
        "query_template": (
            'nwr["amenity"~"^(school|college|university|kindergarten|training|language_school|research_institute)$"]({s},{w},{n},{e});'
        )
    },
    {
        "field": "tourism",
        "category_group": "TOURISM",
        "description": "Hotels, resorts, museums, landmarks, and tourist attractions",
        "query_template": 'nwr["tourism"]({s},{w},{n},{e});'
    },
    {
        "field": "food",
        "category_group": "FOOD",
        "description": "Restaurants, cafes, bakeries, bars, and culinary services",
        "query_template": (
            'nwr["amenity"~"^(restaurant|cafe|fast_food|bar|pub|food_court)$"]({s},{w},{n},{e});\n'
            '  nwr["shop"~"^(bakery|butcher)$"]({s},{w},{n},{e});'
        )
    },
    {
        "field": "leisure",
        "category_group": "LEISURE",
        "description": "Theatres, cinemas, athletic gyms, parks, and recreational facilities",
        "query_template": (
            'nwr["leisure"]({s},{w},{n},{e});\n'
            '  nwr["amenity"~"^(cinema|theatre)$"]({s},{w},{n},{e});'
        )
    },
    {
        "field": "transport",
        "category_group": "TRANSPORT",
        "description": "Airports, train stations, logistics depots, transit hubs, and fuel stations",
        "query_template": (
            'nwr["aeroway"]({s},{w},{n},{e});\n'
            '  nwr["railway"="station"]({s},{w},{n},{e});\n'
            '  nwr["public_transport"]({s},{w},{n},{e});\n'
            '  nwr["amenity"~"^(parking|charging_station|fuel|bus_station|taxi|bicycle_rental)$"]({s},{w},{n},{e});'
        )
    },
    {
        "field": "man_made",
        "category_group": "MAN_MADE",
        "description": "Telecommunications towers, water towers, and utility infrastructure",
        "query_template": 'nwr["man_made"]({s},{w},{n},{e});'
    },
    {
        "field": "organizations",
        "category_group": "ORGANIZATIONS",
        "description": "Non-profit foundations, NGOs, associations, and social centers",
        "query_template": (
            'nwr["club"]({s},{w},{n},{e});\n'
            '  nwr["amenity"~"^(community_centre|social_centre|place_of_worship)$"]({s},{w},{n},{e});\n'
            '  nwr["office"~"^(association|foundation|ngo)$"]({s},{w},{n},{e});'
        )
    }
]

FIELD_BY_NAME: Dict[str, Dict[str, Any]] = {f["field"]: f for f in FIELDS_TAXONOMY}


def slugify(text: str) -> str:
    """Return filesystem-safe lowercase slug."""
    return "".join(c if c.isalnum() else "_" for c in text.strip().lower()).strip("_")


def get_state_bbox(state_name_or_code: str) -> Optional[Tuple[float, float, float, float]]:
    """Resolves bounding box by state name or 2-letter state code."""
    cleaned = state_name_or_code.strip()
    if cleaned.upper() in CODE_TO_STATE:
        name = CODE_TO_STATE[cleaned.upper()]
        return STATE_BOUNDING_BOXES.get(name)
    title_name = cleaned.title()
    return STATE_BOUNDING_BOXES.get(title_name)


def get_field_info(field_name: str) -> Optional[Dict[str, Any]]:
    """Returns taxonomy metadata for a field name."""
    return FIELD_BY_NAME.get(field_name.strip().lower())
