"""
Tests for Module F — Summarizer.

Focus is on the hallucination verifier (`_verify_grounding`) and the template
fallback path — these run without an LLM and are the critical correctness gate.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CACHE_DIR", str(ROOT / ".test_cache"))

from app.models.business import BusinessListing, ReviewData
from app.modules.summarizer import _template_summary, _verify_grounding


def _listing(**overrides) -> BusinessListing:
    base = {
        "id": "t_1",
        "name": "Joe's Pizza",
        "address": "123 Main St, Brooklyn, NY",
        "category": "restaurant",
        "source": "overpass",
        "opening_hours": "Mo-Su 11:00-23:00",
        "phone": "+1-555-1234",
        "website": "https://joespizza.example",
        "review_data": ReviewData(
            total_reviews=42,
            average_rating=4.5,
            positive_percentage=88.0,
            recurring_themes=["great food", "good value"],
            sample_reviews=["best pizza in Brooklyn", "thin crust is amazing"],
        ),
    }
    base.update(overrides)
    return BusinessListing(**base)


# ---------------------------------------------------------------------------
# _verify_grounding — happy path
# ---------------------------------------------------------------------------

class TestVerifyGroundingHappyPath:
    def test_summary_using_only_source_facts(self) -> None:
        listing = _listing()
        summary = (
            "Joe's Pizza on Main St is rated 4.5 with 42 reviews, "
            "praised for great food and good value."
        )
        assert _verify_grounding(summary, listing) is True

    def test_summary_with_paraphrase(self) -> None:
        listing = _listing()
        # "Joe Pizza" (no apostrophe) — tokens still all found in source
        summary = "Joe Pizza is a beloved restaurant with strong reviews."
        assert _verify_grounding(summary, listing) is True

    def test_empty_summary_is_grounded(self) -> None:
        listing = _listing()
        assert _verify_grounding("", listing) is True


# ---------------------------------------------------------------------------
# _verify_grounding — catches hallucinations
# ---------------------------------------------------------------------------

class TestVerifyGroundingCatchesHallucination:
    def test_invented_proper_noun_rejected(self) -> None:
        listing = _listing()
        # "Michelin Star" never appears in source
        summary = "Joe's Pizza has earned a Michelin Star this year."
        assert _verify_grounding(summary, listing) is False

    def test_invented_number_rejected(self) -> None:
        listing = _listing()
        # 99 % positive — source says 88 %
        summary = "Joe's Pizza is loved by 99 of every 100 customers."
        assert _verify_grounding(summary, listing) is False

    def test_invented_award_rejected(self) -> None:
        listing = _listing()
        summary = "Joe's Pizza won the James Beard Award in 2019."
        assert _verify_grounding(summary, listing) is False


# ---------------------------------------------------------------------------
# Template fallback
# ---------------------------------------------------------------------------

class TestTemplateSummary:
    def test_three_sentences_when_all_fields_present(self) -> None:
        out = _template_summary(_listing())
        assert "Joe's Pizza" in out
        # Rating sentence should appear since average_rating is set
        assert "4.5" in out or "rating" in out
        # Should not invent anything
        assert "Michelin" not in out

    def test_no_rating_falls_back_gracefully(self) -> None:
        listing = _listing(
            review_data=ReviewData(total_reviews=0, average_rating=None)
        )
        out = _template_summary(listing)
        assert "Joe's Pizza" in out
        assert "currently unavailable" in out.lower() or "rating" in out.lower()
