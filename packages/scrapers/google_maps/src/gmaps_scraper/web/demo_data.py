import json
from pathlib import Path
from typing import Optional
from ..db import Database

def _load_demo_places():
    json_path = Path(__file__).resolve().parent / 'demo_places.json'
    if json_path.exists():
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

DEMO_PLACES = _load_demo_places()

def seed_demo_data(db: Database, photos_dir: Optional[Path] = None, force: bool = False):
    """Seeds rich sample data if DB is empty or force=True."""
    with db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM places").fetchone()[0]
        if count > 0 and not force:
            return

    for p in DEMO_PLACES:
        db.upsert_place_stub(p)
        if p.get("error"):
            db.mark_place_failed(p["cid"], p["error"])

    # Seed Hours for 787 Coffee
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    cid_787 = "11785376804253324318"
    hours_list = [
        {"day": i+1, "day_name": day, "formatted_text": "7 AM – 8 PM", "is_closed": False}
        for i, day in enumerate(days)
    ]
    # Seed Attributes for 787 Coffee
    attrs_list = [
        {"group_id": "accessibility", "group_name": "Accessibility", "attribute_id": "restroom", "attribute_name": "Wheelchair accessible restroom", "is_enabled": True, "display_value": "Wheelchair accessible restroom"},
        {"group_id": "accessibility", "group_name": "Accessibility", "attribute_id": "seating", "attribute_name": "Wheelchair accessible seating", "is_enabled": True, "display_value": "Wheelchair accessible seating"},
        {"group_id": "service", "group_name": "Service options", "attribute_id": "takeout", "attribute_name": "Takeout", "is_enabled": True, "display_value": "Takeout"},
        {"group_id": "service", "group_name": "Service options", "attribute_id": "dine_in", "attribute_name": "Dine-in", "is_enabled": True, "display_value": "Dine-in"},
        {"group_id": "payments", "group_name": "Payments", "attribute_id": "nfc", "attribute_name": "NFC mobile payments", "is_enabled": True, "display_value": "NFC mobile payments"},
        {"group_id": "amenities", "group_name": "Amenities", "attribute_id": "wifi", "attribute_name": "Free Wi-Fi", "is_enabled": True, "display_value": "Free Wi-Fi"},
    ]
    # Popular times
    pop_times = [
        {"day_idx": 2, "hour_idx": h, "popularity_pct": pop}
        for h, pop in [(7, 25), (8, 65), (9, 90), (10, 80), (11, 60), (12, 75), (13, 70), (14, 55), (15, 45), (16, 35), (17, 30), (18, 20)]
    ]

    db.update_place_details(cid_787, {
        "timezone": "America/New_York",
        "claimed_status": 1,
        "photo_thumbnail": "https://lh3.googleusercontent.com/p/AF1QipNdemo1",
        "rating": 4.8,
        "review_count": 4144,
        "hours": hours_list,
        "attributes": attrs_list,
        "popular_times": pop_times,
    }, status="complete")

    # Seed Reviews for 787 Coffee
    sample_reviews = [
        {
            "review_id": "rev_001",
            "cid": cid_787,
            "author_name": "pit & pon",
            "author_id": "100356873384583317650",
            "author_avatar_url": None,
            "author_profile_url": "https://www.google.com/maps/contrib/100356873384583317650",
            "rating": 5,
            "relative_date": "7 months ago",
            "timestamp_ms": 1772391367100,
            "text": "I absolutely love the dulce de leche, it's so good! We also loved the pastry filled with cream cheese. Everything was freshly brewed and the staff was delightful.",
            "language": "en",
            "owner_response_text": "Hi Yvonne! We're so happy you enjoyed the dulce de leche ice cream and our treats!",
            "owner_response_date": "7 months ago",
            "reaction_count": 3,
            "photos_json": json.dumps(["https://lh3.googleusercontent.com/p/AF1QipNsample1.jpg"])
        },
        {
            "review_id": "rev_002",
            "cid": cid_787,
            "author_name": "Arun Venkatraman",
            "author_id": "10987654321",
            "author_avatar_url": None,
            "author_profile_url": None,
            "rating": 4,
            "relative_date": "1 year ago",
            "timestamp_ms": 1740000000000,
            "text": "Great specialty coffee right in the middle of Wall Street. Fast service and authentic beans.",
            "language": "en",
            "owner_response_text": None,
            "owner_response_date": None,
            "reaction_count": 1,
            "photos_json": "[]"
        },
        {
            "review_id": "rev_003_xss",
            "cid": "11785376804253324399",
            "author_name": "<script>alert('author')</script>",
            "author_id": "xss_author",
            "author_avatar_url": None,
            "author_profile_url": None,
            "rating": 5,
            "relative_date": "Just now",
            "timestamp_ms": 1780000000000,
            "text": "<b onclick=alert('click')>Review injection payload</b>",
            "language": "en",
            "owner_response_text": "<iframe src=javascript:alert('reply')></iframe>",
            "owner_response_date": "Just now",
            "reaction_count": 99,
            "photos_json": "[]"
        }
    ]
    for rev in sample_reviews:
        db.insert_review(rev)

    # Create dummy local photo for 787 Coffee
    if photos_dir:
        p_dir = Path(photos_dir) / cid_787
        p_dir.mkdir(parents=True, exist_ok=True)
        photo_file = p_dir / "photo_demo1.jpg"
        if not photo_file.exists():
            # Minimal 1x1 JPEG byte stream
            minimal_jpg = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9'
            with open(photo_file, "wb") as f:
                f.write(minimal_jpg)

        db.insert_photo({
            "cid": cid_787,
            "review_id": "rev_001",
            "photo_url": "https://lh3.googleusercontent.com/p/AF1QipNsample1.jpg",
            "local_path": str(photo_file),
            "attribution": "pit & pon",
            "file_size": len(minimal_jpg)
        })

    # Record a demo run_state
    with db.get_connection() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO run_state (
                run_id, query, bbox, status, current_step,
                total_discovered, total_enriched, total_reviews, total_photos,
                errors_count, start_time, end_time, last_active, meta_json
            ) VALUES (
                'run_demo_01', 'coffee', '40.70,-74.02,0.02', 'completed', 'export',
                6, 4, 3, 1, 1, datetime('now', '-1 hour'), datetime('now', '-50 minutes'), datetime('now'),
                '{"note": "Demo seeding completed"}'
            )
        """)
        conn.commit()
