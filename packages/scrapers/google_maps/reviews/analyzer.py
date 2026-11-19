"""
DataExtraction — Google Maps Review Analyzer
============================================
Independent review analysis engine. Operates directly on stored reviews in
`staging_dataextraction.place_reviews`.
Extracts:
- Sentiment (positive | neutral | negative | mixed)
- Review topics and keyword clusters
- Customer complaints and customer praise
- Frequently mentioned services
- Customer experience indicators (staff, quality, value, timeliness)
- Place-level aggregate rating distributions and sentiment trends over time
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("dataextraction.gmaps.reviews.analyzer")

# Lexicons for deterministic sentiment and experience indicator tagging
_POSITIVE_WORDS = {
    "great", "excellent", "amazing", "wonderful", "fantastic", "outstanding", "superb",
    "love", "best", "perfect", "friendly", "helpful", "professional", "clean", "fast",
    "efficient", "recommended", "awesome", "prompt", "delicious", "reliable", "honest",
}

_NEGATIVE_WORDS = {
    "terrible", "horrible", "awful", "worst", "bad", "poor", "rude", "unprofessional",
    "dirty", "slow", "expensive", "overpriced", "scam", "cheat", "disappointed", "waste",
    "never", "complaint", "broken", "unresponsive", "delayed", "useless", "avoid",
}

_TOPIC_KEYWORDS = {
    "pricing": ["price", "cost", "charge", "expensive", "cheap", "affordable", "quote", "rate", "fee", "bill"],
    "customer_service": ["service", "staff", "manager", "support", "reception", "team", "personnel", "employee"],
    "quality": ["quality", "workmanship", "detail", "finish", "craftsmanship", "standard", "flawless"],
    "timeliness": ["time", "quick", "fast", "slow", "delay", "wait", "punctual", "late", "schedule", "prompt"],
    "cleanliness": ["clean", "dirty", "spotless", "neat", "hygiene", "mess", "tidy", "sanitary"],
    "communication": ["communication", "called", "email", "phone", "answer", "inform", "update", "explained"],
}

_SERVICE_INDICATORS = {
    "consulting": ["consult", "advice", "guidance", "recommendation"],
    "installation": ["install", "installation", "setup", "mounting"],
    "repair": ["repair", "fix", "fixed", "replacement", "serviced"],
    "maintenance": ["maintenance", "tuneup", "inspection", "checkup"],
    "delivery": ["delivery", "shipping", "shipped", "arrived"],
    "support": ["support", "troubleshoot", "assistance", "help"],
    "catering": ["cater", "catering", "buffet", "food service"],
    "booking": ["reservation", "booking", "appointment", "scheduled"],
}


class ReviewAnalyzer:
    def __init__(
        self,
        get_conn_fn: Callable[[], Any],
        release_conn_fn: Callable[[Any], None],
        model_name: str = "hybrid-lexicon-v1",
    ):
        self._get_conn = get_conn_fn
        self._release_conn = release_conn_fn
        self._model_name = model_name

    def analyze_review_text(self, text: Optional[str], rating: Optional[int]) -> Dict[str, Any]:
        """Analyzes a single review text + rating deterministically."""
        clean_text = (text or "").strip().lower()
        words = set(re.findall(r"\b[a-z]{3,}\b", clean_text))

        pos_matches = words.intersection(_POSITIVE_WORDS)
        neg_matches = words.intersection(_NEGATIVE_WORDS)

        # Sentiment resolution taking into account explicit star rating
        if rating is not None and rating >= 4:
            if len(neg_matches) > len(pos_matches) and len(neg_matches) >= 2:
                sentiment = "mixed"
            else:
                sentiment = "positive"
        elif rating is not None and rating <= 2:
            if len(pos_matches) > len(neg_matches) and len(pos_matches) >= 2:
                sentiment = "mixed"
            else:
                sentiment = "negative"
        else:
            if len(pos_matches) > 0 and len(neg_matches) > 0:
                sentiment = "mixed"
            elif len(pos_matches) > len(neg_matches):
                sentiment = "positive"
            elif len(neg_matches) > len(pos_matches):
                sentiment = "negative"
            else:
                sentiment = "neutral"

        # Topic detection
        topics = []
        for topic, kws in _TOPIC_KEYWORDS.items():
            if any(kw in clean_text for kw in kws):
                topics.append(topic)

        # Complaints and praise extraction
        complaints = []
        praise = []
        sentences = re.split(r"[.!?\n]+", text or "")
        for s in sentences:
            s_clean = s.strip()
            s_low = s_clean.lower()
            if not s_clean:
                continue
            if any(w in s_low for w in _NEGATIVE_WORDS) and (sentiment in ("negative", "mixed") or rating in (1, 2, 3)):
                complaints.append(s_clean[:250])
            elif any(w in s_low for w in _POSITIVE_WORDS) and (sentiment in ("positive", "mixed") or rating in (4, 5)):
                praise.append(s_clean[:250])

        # Frequently mentioned services
        mentioned_services = []
        for svc, kws in _SERVICE_INDICATORS.items():
            if any(kw in clean_text for kw in kws):
                mentioned_services.append(svc)

        # Customer experience indicators
        cx_indicators = {
            "staff_friendly": ("friendly" in words or "helpful" in words) and "rude" not in words,
            "timely_service": ("fast" in words or "quick" in words or "prompt" in words) and "slow" not in words,
            "high_quality": "great" in words or "excellent" in words or "perfect" in words,
            "good_value": ("affordable" in words or "reasonable" in words) and "overpriced" not in words,
        }

        confidence = 0.90 if rating is not None and text else 0.75

        return {
            "sentiment": sentiment,
            "topics": topics,
            "complaints": complaints[:5],
            "praise": praise[:5],
            "frequently_mentioned_services": mentioned_services,
            "customer_experience_indicators": cx_indicators,
            "analysis_confidence": confidence,
            "analysis_model": self._model_name,
        }

    def analyze_stored_reviews(
        self,
        place_id: Optional[str] = None,
        limit: int = 500,
        reanalyze: bool = False,
    ) -> Dict[str, Any]:
        """
        Processes unanalyzed reviews (or all reviews if reanalyze=True)
        and persists analysis metadata without modifying original text.
        """
        conn = self._get_conn()
        if not conn:
            return {"status": "error", "message": "Database connection unavailable"}

        try:
            with conn.cursor() as cur:
                where_clauses = []
                params: List[Any] = []
                if place_id:
                    where_clauses.append("place_id = %s")
                    params.append(place_id)
                if not reanalyze:
                    where_clauses.append("analyzed_at IS NULL")

                where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
                cur.execute(
                    f"""
                    SELECT id, place_id, review_id, rating, review_text
                    FROM staging_dataextraction.place_reviews
                    {where_sql}
                    ORDER BY published_at DESC NULLS LAST
                    LIMIT %s
                    """,
                    (*params, limit),
                )
                rows = cur.fetchall()

            if not rows:
                return {"status": "complete", "analyzed_count": 0}

            updates = []
            for (pk_id, p_id, r_id, rating, r_text) in rows:
                insights = self.analyze_review_text(r_text, rating)
                updates.append((
                    pk_id,
                    insights["sentiment"],
                    json.dumps(insights["topics"]),
                    json.dumps(insights["complaints"]),
                    json.dumps(insights["praise"]),
                    json.dumps(insights["frequently_mentioned_services"]),
                    json.dumps(insights["customer_experience_indicators"]),
                    insights["analysis_confidence"],
                    insights["analysis_model"],
                    datetime.now(timezone.utc),
                ))

            with conn.cursor() as cur:
                from psycopg2.extras import execute_values
                execute_values(
                    cur,
                    """
                    UPDATE staging_dataextraction.place_reviews AS pr SET
                        sentiment = val.sentiment,
                        topics = val.topics::jsonb,
                        complaints = val.complaints::jsonb,
                        praise = val.praise::jsonb,
                        frequently_mentioned_services = val.frequently_mentioned_services::jsonb,
                        customer_experience_indicators = val.customer_experience_indicators::jsonb,
                        analysis_confidence = val.analysis_confidence,
                        analysis_model = val.analysis_model,
                        analyzed_at = val.analyzed_at
                    FROM (VALUES %s) AS val(id, sentiment, topics, complaints, praise, frequently_mentioned_services, customer_experience_indicators, analysis_confidence, analysis_model, analyzed_at)
                    WHERE pr.id = val.id
                    """,
                    updates,
                )
            conn.commit()
            return {"status": "complete", "analyzed_count": len(updates)}

        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error("Error analyzing reviews: %s", exc)
            return {"status": "error", "error": str(exc), "analyzed_count": 0}
        finally:
            self._release_conn(conn)

    def get_place_review_summary(self, place_id: str) -> Dict[str, Any]:
        """Calculates place-level aggregate sentiment, rating distribution and trends."""
        conn = self._get_conn()
        if not conn:
            return {}
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) as total_reviews,
                        AVG(rating) as avg_rating,
                        COUNT(CASE WHEN rating = 5 THEN 1 END) as r5,
                        COUNT(CASE WHEN rating = 4 THEN 1 END) as r4,
                        COUNT(CASE WHEN rating = 3 THEN 1 END) as r3,
                        COUNT(CASE WHEN rating = 2 THEN 1 END) as r2,
                        COUNT(CASE WHEN rating = 1 THEN 1 END) as r1,
                        COUNT(CASE WHEN sentiment = 'positive' THEN 1 END) as pos,
                        COUNT(CASE WHEN sentiment = 'negative' THEN 1 END) as neg,
                        COUNT(CASE WHEN sentiment = 'neutral' THEN 1 END) as neu,
                        COUNT(CASE WHEN sentiment = 'mixed' THEN 1 END) as mix
                    FROM staging_dataextraction.place_reviews
                    WHERE place_id = %s
                    """,
                    (place_id,),
                )
                row = cur.fetchone()
                if not row or row[0] == 0:
                    return {"place_id": place_id, "total_reviews": 0}

                return {
                    "place_id": place_id,
                    "total_reviews": row[0],
                    "average_rating": float(round(row[1], 2)) if row[1] else None,
                    "rating_distribution": {"5": row[2], "4": row[3], "3": row[4], "2": row[5], "1": row[6]},
                    "sentiment_summary": {"positive": row[7], "negative": row[8], "neutral": row[9], "mixed": row[10]},
                }
        except Exception as exc:
            logger.warning("Error fetching place review summary for %s: %s", place_id, exc)
            return {}
        finally:
            self._release_conn(conn)
