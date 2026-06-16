"""
Build a labeled training set for the intent classifier (PDF §7.1).

Generates ~500 labeled queries via template-based augmentation:
  - 10 category buckets × ~20 paraphrased templates × N slot fills
  - Location-type variants (near_me / city / zip / neighborhood)
  - Count variants (small integer or "best" / "top" prefix)
  - Filter combinations (open_now, affordable, highly_rated, etc.)

Run:
    python -m backend.scripts.build_intent_dataset

Writes:  backend/models/intent_classifier/dataset.jsonl
"""

from __future__ import annotations

import itertools
import json
import random
from pathlib import Path
from typing import Dict, List

random.seed(42)

OUT_PATH = Path(__file__).resolve().parents[1] / "models" / "intent_classifier" / "dataset.jsonl"

# (category_label, sample_phrases) — sample_phrases get substituted into templates
CATEGORIES: Dict[str, List[str]] = {
    "restaurant": ["sushi restaurant", "pizza place", "Mexican food", "Italian restaurant", "ramen shop"],
    "cafe": ["coffee shop", "cafe", "espresso bar", "breakfast spot"],
    "bar": ["cocktail bar", "wine bar", "sports bar", "pub"],
    "fitness_centre": ["gym", "fitness studio", "yoga studio", "pilates studio", "CrossFit gym"],
    "dentist": ["dentist", "orthodontist", "dental clinic"],
    "salon": ["hair salon", "barber shop", "nail salon", "beauty parlor"],
    "supermarket": ["grocery store", "supermarket", "organic market"],
    "coworking": ["co-working space", "shared office", "coworking spot"],
    "spa": ["spa", "massage place", "wellness center", "meditation center"],
    "tax_filing": ["tax filing service", "tax accountant", "tax prep company"],
}

# Templates with placeholders {what}, {where}, {count}, {filter}
TEMPLATES = [
    "find me {count} {what} {where}",
    "best {count} {what} {where}",
    "top {count} {what} {where}",
    "show me {count} {what} {where}",
    "I want to find {what} {where}",
    "any {what} {where}?",
    "where can I find {what} {where}",
    "recommend {what} {where}",
    "{what} {where} {filter}",
    "{count} {filter} {what} {where}",
    "list {what} {where}",
    "{what} {filter}",
    "good {what} {where}",
    "{count} highly rated {what} {where}",
    "looking for {what} {where}",
]

LOCATIONS = [
    ("near_me", ["near me", "nearby", "close to me", "around me", ""]),
    ("city", ["in San Francisco", "in Austin", "in Seattle", "in NYC", "in Boston", "in Chicago"]),
    ("zip", ["near 10001", "in zip 94110", "near zip 78701", "around 02115"]),
    ("neighborhood", ["in downtown Austin", "in SoHo", "in Capitol Hill", "in the Mission"]),
]

COUNTS = ["3", "5", "10", "best 3", "top 5", ""]
FILTERS = [
    ("open_now", ["open now", "open right now", "open today"]),
    ("affordable", ["affordable", "cheap", "budget-friendly"]),
    ("highly_rated", ["highly rated", "5-star", "top rated"]),
    ("", [""]),
]


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows: List[dict] = []

    for cat_label, what_phrases in CATEGORIES.items():
        for what in what_phrases:
            for loc_label, loc_phrases in LOCATIONS:
                for filter_label, filter_phrases in FILTERS:
                    for count in COUNTS:
                        tpl = random.choice(TEMPLATES)
                        where = random.choice(loc_phrases)
                        filt = random.choice(filter_phrases)
                        query = tpl.format(what=what, where=where, count=count, filter=filt)
                        # Tidy whitespace and stray punctuation
                        query = " ".join(query.split()).rstrip("?,.").strip()
                        if not query or len(query) < 5:
                            continue
                        rows.append(
                            {
                                "query": query,
                                "category": cat_label,
                                "location_type": loc_label,
                                "filters": [filter_label] if filter_label else [],
                            }
                        )

    random.shuffle(rows)
    with OUT_PATH.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"Wrote {len(rows)} labeled queries → {OUT_PATH}")


if __name__ == "__main__":
    main()
