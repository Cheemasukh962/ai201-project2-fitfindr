"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import json
import re

from tools import (
    search_listings,
    suggest_outfit,
    create_fit_card,
    _get_groq_client,
)


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── query parsing ─────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """
    Use the LLM (temperature 0) to extract structured search parameters from a
    free-text request, returning {"description", "size", "max_price"}.

    Falls back to {"description": query, "size": None, "max_price": None} on ANY
    failure (bad JSON, network error, etc.) so a bad parse never crashes the run.
    """
    prompt = (
        "Extract thrift-search parameters from the request below. "
        "Respond with ONLY a JSON object, no prose, using exactly these keys:\n"
        '  "description": string of item keywords (no size/price words)\n'
        '  "size": a size string like "M" or "8", or null if not mentioned\n'
        '  "max_price": a number, or null if not mentioned\n\n'
        f"Request: {query}\n\n"
        'Example -> {"description": "vintage graphic tee", "size": "M", "max_price": 30}'
    )
    try:
        client = _get_groq_client()
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        text = (resp.choices[0].message.content or "").strip()
        # Pull the first {...} block out of the reply (handles ```json fences / prose).
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        data = json.loads(match.group(0)) if match else {}

        size = data.get("size")
        max_price = data.get("max_price")
        if max_price is not None:
            try:
                max_price = float(max_price)
            except (TypeError, ValueError):
                max_price = None
        return {
            "description": data.get("description") or query,
            "size": str(size) if size is not None else None,
            "max_price": max_price,
        }
    except Exception:
        # Defensive fallback: search on the raw query with no filters.
        return {"description": query, "size": None, "max_price": None}


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    session = _new_session(query, wardrobe)

    # Step 2: parse the free-text query into description / size / max_price.
    session["parsed"] = _parse_query(query)
    p = session["parsed"]

    # Step 3: search. The planning decision lives here — empty results stop the run.
    results = search_listings(p["description"], p.get("size"), p.get("max_price"))
    session["search_results"] = results
    if not results:
        size_txt = f' in size {p["size"]}' if p.get("size") else ""
        price_txt = f' under ${p["max_price"]:g}' if p.get("max_price") else ""
        session["error"] = (
            f'No listings matched "{p["description"]}"{size_txt}{price_txt}. '
            "Try removing the size filter, raising your max price, or using broader keywords."
        )
        return session

    # Step 4: pick the top-ranked match.
    session["selected_item"] = results[0]

    # Step 5: outfit built from the selected item + the user's wardrobe.
    session["outfit_suggestion"] = suggest_outfit(session["selected_item"], wardrobe)

    # Step 6: shareable fit card built from the outfit + the item.
    session["fit_card"] = create_fit_card(
        session["outfit_suggestion"], session["selected_item"]
    )

    # Step 7: return the completed session.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    # State check — the exact session fields handed from one tool to the next.
    print("\n-- state passed between tools --")
    item = session["selected_item"]
    outfit = session["outfit_suggestion"] or ""
    print(f"  selected_item id : {item['id'] if item else None}")
    print(f"  outfit_suggestion: {len(outfit)} chars")
    print(f"  fit_card         : {'present' if session['fit_card'] else None}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
    # The branch must stop early: downstream tools never ran, so these stay None.
    print("\n-- state after early return --")
    print(f"  selected_item    : {session2['selected_item']}")
    print(f"  outfit_suggestion: {session2['outfit_suggestion']}")
    print(f"  fit_card         : {session2['fit_card']}")
