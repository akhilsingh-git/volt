"""
Volt clip recommender — a small, self-contained content recommender.

Builds a synthetic clip catalog across a handful of categories and serves two
kinds of feeds:
  * trending  — top clips by score (cold start / unknown users)
  * for-you   — clips from the categories a user has watched, ranked by score

No external model files or services; everything is generated in-process.
"""
import random

CATEGORIES = ["1000", "1001", "1002", "13266", "20097", "70323", "264017"]
CLIPS_PER_CATEGORY = 14

_rng = random.Random(11)

# catalog: clip_uid -> {"category", "score"}
CATALOG = {}
for _cat in CATEGORIES:
    for _i in range(CLIPS_PER_CATEGORY):
        uid = "c_{}_{:03d}".format(_cat, _i)
        CATALOG[uid] = {"category": _cat, "score": round(_rng.uniform(1, 100), 2)}

# demo users with a watch history → exercise the personalized path
WATCH_HISTORY = {
    "demo": ["c_1000_001", "c_1000_004", "c_20097_002", "c_13266_005"],
}

MAX_RESULTS = 80


def _trending(category=""):
    items = [(u, m["score"]) for u, m in CATALOG.items()
             if not category or m["category"] == category]
    items.sort(key=lambda x: -x[1])
    return {u: s for u, s in items[:MAX_RESULTS]}


def recommend(user_id, custom_clips=None, category=""):
    """
    Returns (is_generic, {clip_uid: score}).
    `custom_clips` lets a caller pass a watch history for a cold-start user.
    """
    history = WATCH_HISTORY.get(user_id) or list(custom_clips or [])
    if not history:
        return True, _trending(category)

    watched_categories = {CATALOG[c]["category"] for c in history if c in CATALOG}
    if category:
        watched_categories = {category}

    recs = {u: m["score"] for u, m in CATALOG.items()
            if m["category"] in watched_categories and u not in history}

    if len(recs) < 10:                       # too thin → fall back to trending
        return False, _trending(category)

    ranked = dict(sorted(recs.items(), key=lambda x: -x[1])[:MAX_RESULTS])
    return False, ranked
