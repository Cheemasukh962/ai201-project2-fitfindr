"""
Isolation tests for the three FitFindr tools.

Run from the project root:
    pytest tests/

The search tests are deterministic and need no API. The suggest_outfit test makes
one live Groq call, so it auto-skips if GROQ_API_KEY is not set.
"""

import os

import pytest

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_empty_wardrobe

# Skip the live-call test gracefully when no key is available (e.g. CI / grading).
needs_key = pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="requires GROQ_API_KEY for a live Groq call",
)


# ── search_listings — deterministic, no API ──────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # Nothing is under $5 and there are no ballgowns / XXS -> empty list, no exception.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_token_match():
    # size="M" keeps "S/M" items and drops L-only items via smart token matching.
    results = search_listings("graphic", size="M", max_price=None)
    ids = {item["id"] for item in results}
    assert "lst_002" in ids        # size "S/M" -> token set contains M
    assert "lst_006" not in ids    # size "L"   -> correctly excluded


# ── create_fit_card failure mode — deterministic, no API ─────────────────────

def test_create_fit_card_empty_outfit():
    # Empty outfit -> descriptive error string, never an exception or empty string.
    item = search_listings("vintage graphic tee", None, 50)[0]
    result = create_fit_card("", item)
    assert isinstance(result, str)
    assert "fit card" in result.lower()


# ── suggest_outfit failure mode — one live Groq call ─────────────────────────

@needs_key
def test_suggest_outfit_empty_wardrobe():
    # Empty wardrobe -> useful, non-empty general advice (not a crash or "").
    item = search_listings("vintage graphic tee", None, 50)[0]
    result = suggest_outfit(item, get_empty_wardrobe())
    assert isinstance(result, str)
    assert result.strip() != ""
