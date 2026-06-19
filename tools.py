"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    # Step 2: price filter (inclusive). Skipped when max_price is None.
    if max_price is not None:
        listings = [item for item in listings if item["price"] <= max_price]

    # Step 2: size filter via smart token match. Split each listing's messy
    # size string on non-alphanumerics so "S/M" -> {S, M}, "US 8.5" -> {US, 8, 5}.
    # Keep a listing only if the requested size is one of those tokens.
    if size is not None:
        wanted = size.strip().upper()
        listings = [
            item
            for item in listings
            if wanted in set(re.split(r"[^A-Z0-9]+", item["size"].upper()))
        ]

    # Step 3: score by weighted keyword overlap — tags x2, title x1, description x1.
    keywords = [w for w in re.split(r"\W+", description.lower()) if w]
    scored: list[tuple[int, dict]] = []
    for item in listings:
        tags = " ".join(item["style_tags"]).lower()
        title = item["title"].lower()
        desc = item["description"].lower()
        score = sum(
            (2 if kw in tags else 0)
            + (1 if kw in title else 0)
            + (1 if kw in desc else 0)
            for kw in keywords
        )
        # Step 4: drop listings with no keyword relevance.
        if score > 0:
            scored.append((score, item))

    # Step 5: sort by score, highest first (stable for ties), and return the dicts.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    items = wardrobe.get("items", []) if isinstance(wardrobe, dict) else []

    # Describe the new item once, reused by both prompt branches.
    item_desc = (
        f'{new_item.get("title", "this item")} '
        f'(category: {new_item.get("category", "?")}, '
        f'colors: {", ".join(new_item.get("colors", [])) or "n/a"}, '
        f'style: {", ".join(new_item.get("style_tags", [])) or "n/a"})'
    )

    if not items:
        # Failure-mode branch: empty wardrobe -> general styling advice.
        prompt = (
            f"A shopper is considering this secondhand item:\n  {item_desc}\n\n"
            "They have not entered their wardrobe yet. Give friendly, general styling "
            "advice: the overall vibe this piece suits, and 2-3 kinds of items "
            "(by type and color, not specific brands) that would pair well with it. "
            "Keep it to 3-4 sentences, warm and practical."
        )
    else:
        # Wardrobe-first branch: build outfits around owned pieces, named explicitly.
        wardrobe_lines = "\n".join(
            f'  - {it.get("name", "?")} · {it.get("category", "?")} · '
            f'{", ".join(it.get("style_tags", [])) or "n/a"}'
            for it in items
        )
        prompt = (
            f"A shopper found this secondhand item:\n  {item_desc}\n\n"
            f"Their current wardrobe:\n{wardrobe_lines}\n\n"
            "Suggest 1-2 complete outfits built around the NEW item. Draw mainly from the "
            "owned pieces listed above and name them exactly as written. You may suggest at "
            "most ONE item they do not own to finish a look, but clearly flag it as not in "
            "their closet. Keep it concise (a short paragraph per outfit) and practical."
        )

    # Single LLM call, guarded so the tool always returns a usable, non-empty string.
    try:
        client = _get_groq_client()
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a thoughtful personal stylist who "
                                              "specializes in secondhand and vintage fashion."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=400,
        )
        out = (resp.choices[0].message.content or "").strip()
    except Exception:
        out = ""

    if not out:
        return (
            "Couldn't generate a full outfit right now — try pairing it with neutral "
            "basics and your go-to shoes."
        )
    return out


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # Required failure mode: empty/whitespace outfit -> error string, no LLM call.
    if not outfit or not outfit.strip():
        return "Can't make a fit card yet — no outfit was generated to caption."

    title = new_item.get("title", "this piece")
    price = new_item.get("price", "?")
    platform = new_item.get("platform", "online")

    prompt = (
        "Write a short, shareable outfit caption for a thrifted find.\n"
        f"Item: {title}\n"
        f"Price: ${price}\n"
        f"Platform: {platform}\n"
        f"Outfit: {outfit}\n\n"
        "Voice: polished and punchy, like a curated OOTD post — proper capitalization, a "
        "clean hook line, optional 1-2 hashtags. 2-4 sentences. Mention the item name, price, "
        "and platform once each, naturally. Capture the outfit's vibe in specific terms. "
        "Sound like a real post, not a product description. Make it fresh and original."
    )

    # High temperature so different inputs (and reruns) produce different captions.
    try:
        client = _get_groq_client()
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You write catchy, authentic fashion captions "
                                              "for secondhand finds."},
                {"role": "user", "content": prompt},
            ],
            temperature=1.0,
            max_tokens=200,
        )
        out = (resp.choices[0].message.content or "").strip()
    except Exception:
        out = ""

    if not out:
        return "Couldn't write a fit card right now — give it another try in a moment."
    return out
