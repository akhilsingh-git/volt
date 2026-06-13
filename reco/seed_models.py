"""
Local seed for turing's clip recommender.

The real models (recommenders/models/{watch_history_graph,video_score_matrix}.sav)
were trained offline and stored in S3 — they are NOT in the repo. This script
generates small synthetic .sav files with the *exact* structures the unmodified
recommender expects, so the real recommendation logic runs locally on demo data:

  G           : networkx.Graph. Edge user->clip means "user watched clip".
                Used via G.has_node("u_<id>") and G.neighbors("u_<id>").
  ScoreMatrix : { clip_uid: {
                    "information": {"Maxscore": float, "Category": "<cat_id>"},
                    "relation":    { other_clip_uid: score, ... }
                }}
"""
import os
import pickle
import random

import networkx as nx

random.seed(7)

# A subset of the categories the recommender knows about (incl. freefire 20097,
# which the code special-cases).
CATEGORIES = ["20097", "1000", "1001", "1002", "13266", "70323", "264017"]
CLIPS_PER_CATEGORY = 12

models_dir = os.path.join(os.getcwd(), "recommenders", "models")
os.makedirs(models_dir, exist_ok=True)

# ── Build clips + ScoreMatrix ────────────────────────────────────────────────
clips = []
ScoreMatrix = {}
for cat in CATEGORIES:
    for i in range(CLIPS_PER_CATEGORY):
        uid = "c_{}_{:03d}".format(cat, i)
        clips.append((uid, cat))
        ScoreMatrix[uid] = {
            "information": {"Maxscore": round(random.uniform(1, 100), 2), "Category": cat},
            "relation": {},
        }

# Each clip relates to a handful of others (weighted toward same category).
for uid, cat in clips:
    same_cat = [c for c, cc in clips if cc == cat and c != uid]
    others = [c for c, cc in clips if cc != cat]
    related = random.sample(same_cat, min(6, len(same_cat))) + random.sample(others, 3)
    for r in related:
        ScoreMatrix[uid]["relation"][r] = round(random.uniform(0.1, 1.0), 3)

# ── Build watch-history graph with a couple of demo users ────────────────────
G = nx.Graph()
for uid, _ in clips:
    G.add_node(uid)

# u_demo has watched some freefire + a couple others -> personalized feed
demo_watched = ["c_20097_000", "c_20097_001", "c_20097_004", "c_1000_002", "c_13266_005"]
G.add_node("u_demo")
for c in demo_watched:
    G.add_edge("u_demo", c)

# u_new is intentionally absent -> exercises the cold-start (generic) path.

with open(os.path.join(models_dir, "watch_history_graph.sav"), "wb") as f:
    pickle.dump(G, f)
with open(os.path.join(models_dir, "video_score_matrix.sav"), "wb") as f:
    pickle.dump(ScoreMatrix, f)

print("seeded {} clips across {} categories; users: u_demo (personalized), u_new (cold-start)".format(
    len(clips), len(CATEGORIES)))
