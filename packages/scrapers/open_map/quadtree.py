"""
Adaptive Quadtree Spatial Subdivision Engine for Overpass API Bounding Boxes.
Embedded in OneExtraction platform.
"""

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("OSMQuadtree")


def split_bounding_box(
    bbox: Tuple[float, float, float, float]
) -> List[Tuple[str, Tuple[float, float, float, float]]]:
    """
    Subdivides a bounding box (south, west, north, east) into 4 equal quadrants:
    - q1: South-West (SW)
    - q2: South-East (SE)
    - q3: North-West (NW)
    - q4: North-East (NE)
    """
    s, w, n, e = bbox
    mid_lat = round((s + n) / 2.0, 6)
    mid_lon = round((w + e) / 2.0, 6)

    return [
        ("q1_sw", (s, w, mid_lat, mid_lon)),
        ("q2_se", (s, mid_lon, mid_lat, e)),
        ("q3_nw", (mid_lat, w, n, mid_lon)),
        ("q4_ne", (mid_lat, mid_lon, n, e)),
    ]


class AdaptiveQuadtree:
    """Manages spatial subdivision hierarchy and record aggregation."""

    def __init__(self, max_depth: int = 3, min_chunk_deg: float = 0.0625):
        self.max_depth = max_depth
        self.min_chunk_deg = min_chunk_deg

    def can_subdivide(
        self,
        bbox: Tuple[float, float, float, float],
        current_depth: int
    ) -> bool:
        if current_depth >= self.max_depth:
            return False

        s, w, n, e = bbox
        lat_span = abs(n - s)
        lon_span = abs(e - w)

        if lat_span / 2.0 < self.min_chunk_deg or lon_span / 2.0 < self.min_chunk_deg:
            return False

        return True

    def create_child_chunks(
        self,
        parent_chunk_id: str,
        parent_bbox: Tuple[float, float, float, float],
        current_depth: int
    ) -> List[Dict[str, Any]]:
        quadrants = split_bounding_box(parent_bbox)
        children = []

        for suffix, sub_bbox in quadrants:
            child_id = f"{parent_chunk_id}_{suffix}"
            children.append({
                "chunk_id": child_id,
                "parent_id": parent_chunk_id,
                "depth": current_depth + 1,
                "bbox": sub_bbox,
                "is_leaf": False
            })

        logger.info(
            f"[QUADTREE] Subdivided {parent_chunk_id} (depth={current_depth}) "
            f"into 4 quadrants: {[c['chunk_id'] for c in children]}"
        )
        return children

    @staticmethod
    def deduplicate_records(
        records_list: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        seen = set()
        deduped = []
        for r in records_list:
            osm_type = r.get("osm_type", "")
            osm_id = str(r.get("osm_id", ""))
            key = f"{osm_type}_{osm_id}"
            if key not in seen and (osm_id or r.get("name")):
                seen.add(key)
                deduped.append(r)
        return deduped
