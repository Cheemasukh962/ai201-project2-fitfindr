# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Filters the 40 mock listings down to those matching the user's keywords, optional size, and optional price ceiling, then ranks the survivors by keyword relevance and returns them best-match-first. Pure data filtering — no LLM call.

**Input parameters:**
- `description` (str): free-text keywords describing the desired item, e.g. `"vintage graphic tee"`. Split into lowercase keywords for relevance scoring.
- `size` (str | None): optional size filter, e.g. `"M"`. `None` skips size filtering. Matched case-insensitively via smart token matching (see logic step 3).
- `max_price` (float | None): optional **inclusive** price ceiling, e.g. `30.0`. `None` skips price filtering.

**What it returns:**
A `list[dict]` of matching listings, sorted by relevance score descending (best match first). Each element is the **full listing dict** with all 11 fields: `id, title, description, category, style_tags, size, condition, price, colors, brand, platform`. Returns `[]` when nothing matches.

**Filtering + scoring logic:**
1. Load all listings with `load_listings()`.
2. **Price filter:** if `max_price` is not None, drop listings where `price > max_price`.
3. **Size filter (smart token match):** if `size` is not None, keep a listing only if `size.upper()` is in the token set `re.split(r"[^A-Z0-9]+", listing["size"].upper())`. So `"S/M"` → `{S, M}`, `"M/L"` → `{M, L}`, `"US 8.5"` → `{US, 8, 5}`. A query of `"M"` matches `M`, `S/M`, `M/L`; it does NOT match `US 7`, `One Size`, or `XL`.
4. **Relevance score (weighted keyword overlap):** lowercase the description and split into keywords; for each keyword, add **+2** if it appears in any `style_tag`, **+1** if it appears in `title`, **+1** if it appears in `description`. (Case-insensitive substring match per keyword.)
5. **Drop** any listing with a total score of 0 (no keyword relevance).
6. **Sort** by score descending and return the listing dicts.

**What happens if it fails or returns nothing:**
Returns an empty list `[]` — it never raises. An empty list is a valid result, not an exception. The planning loop detects it, sets `session["error"]` with a helpful "no matches — try loosening size/price or different keywords" message, and stops **before** calling `suggest_outfit`, so no downstream tool ever receives an empty item.

---

### Tool 2: suggest_outfit

**What it does:**
Uses the LLM to turn a found item plus the user's wardrobe into 1–2 concrete outfit suggestions, building primarily around pieces the user already owns and naming them explicitly. Centerpiece = the new item.

**Input parameters:**
- `new_item` (dict): a single listing dict (chosen by the planning loop, normally `search_results[0]`). The tool anchors the outfit on its `title`, `category`, `colors`, and `style_tags`.
- `wardrobe` (dict): a wardrobe dict shaped `{"items": [ {id, name, category, colors, style_tags, notes}, ... ]}`. May be empty (`items == []`) — this is the handled failure mode.

**What it returns:**
A non-empty `str` describing 1–2 complete outfits in casual prose, referencing wardrobe pieces **by name**. May include **at most one** complementary item the user doesn't own, clearly flagged as a suggestion to add. LLM temperature ~0.7.

**Logic:**
1. If `wardrobe.get("items")` is empty → call the LLM with a *general-styling* prompt (no wardrobe): what vibe the item suits and what kinds of pieces pair well. Return that string.
2. Otherwise → format each wardrobe item as a `name · category · style_tags` line; prompt the LLM to build 1–2 outfits centered on `new_item`, drawing **mainly from the listed owned pieces (named explicitly)**, allowing at most one fill-in item not owned (flagged as such).
3. Return the LLM response string.

**What happens if it fails or returns nothing:**
The empty-wardrobe case is the primary failure mode and is handled by branch 1 (general styling advice instead of crashing or returning `""`). As a second guard, the LLM call is wrapped so that if it raises or returns an empty/whitespace string, the tool returns a safe non-empty fallback (e.g. *"Couldn't generate a full outfit right now — try pairing it with neutral basics and your go-to shoes."*). The function therefore always returns a usable, non-empty string.

---

### Tool 3: create_fit_card

**What it does:**
Uses the LLM to turn an outfit suggestion into a short, shareable caption for the thrifted find — a polished, punchy OOTD post. Built to read like a curated caption, not a product description, and to vary across runs and inputs.

**Input parameters:**
- `outfit` (str): the outfit suggestion string returned by `suggest_outfit()`. Supplies the styling context the caption is built from.
- `new_item` (dict): the listing dict for the thrifted item. The caption pulls `title`, `price`, and `platform` from it (each mentioned once, naturally).

**What it returns:**
A `str` caption, 2–4 sentences, in a **polished/punchy** voice: proper capitalization, a clean hook line, optional 1–2 hashtags. Mentions the item name, price, and platform once each, and captures the outfit vibe in specific terms. LLM temperature ~1.0 so reruns and different inputs produce different captions.

**What happens if it fails or returns nothing:**
If `outfit` is empty or whitespace-only, the tool returns a descriptive **error message string** immediately (e.g. *"Can't make a fit card yet — no outfit was generated to caption."*) — it does not call the LLM and does not raise. The LLM call itself is also guarded so that an exception or empty response returns a safe fallback string rather than crashing.

---

### Additional Tools (if any)

<!-- Copy the block above for any tools beyond the required three -->

---

## Planning Loop

**How does your agent decide which tool to call next?**

The agent runs a **conditional sequential** loop inside `run_agent(query, wardrobe)`. It does **not** call all three tools unconditionally — the empty-results branch in step 3 can end the run early. All state lives in one `session` dict (see State Management).

1. **Initialize** `session = _new_session(query, wardrobe)`.

2. **Parse the query (LLM call).** Call the LLM at temperature 0 with the raw query and a prompt that says to return **only** a JSON object: `{"description": str, "size": str|null, "max_price": number|null}`. Strip any markdown code fences, then `json.loads()` it. Store the result in `session["parsed"]`.
   - **Parse-failure guard:** if the response isn't valid JSON (or the call raises), fall back to `{"description": query, "size": None, "max_price": None}` so search still runs on the raw keywords. A bad parse never crashes the run.

3. **Search.** Call `search_listings(parsed["description"], parsed["size"], parsed["max_price"])` and store the list in `session["search_results"]`.
   - **Branch — this is the planning decision:** if `search_results == []`, set `session["error"]` to a helpful message naming what to loosen (size / price / keywords) and **return the session immediately**. `suggest_outfit` and `create_fit_card` are never called; `selected_item`, `outfit_suggestion`, and `fit_card` stay `None`.

4. **Select item.** `session["selected_item"] = search_results[0]` — the top-ranked match.

5. **Suggest outfit.** Call `suggest_outfit(selected_item, session["wardrobe"])` and store the string in `session["outfit_suggestion"]`.

6. **Create fit card.** Call `create_fit_card(outfit_suggestion, selected_item)` and store the string in `session["fit_card"]`.

7. **Return** `session`. The caller checks `session["error"]` first; if it's `None`, all three output fields are populated.

**How it knows it's done:** the run terminates either at step 3 (early return on empty search) or after step 6 (fit card produced). There is no open-ended iteration — the "loop" is the ordered pipeline plus the conditional early-exit, so the agent's behavior depends on what `search_listings` returned rather than running a fixed sequence every time.

---

## State Management

**How does information from one tool get passed to the next?**

A single `session` dict, created by `_new_session(query, wardrobe)`, is the one source of truth for an interaction. Each step **writes** its output to a session field; later steps **read** from those fields instead of re-deriving anything or re-prompting the user. Information flows tool → session → tool.

| Field | Type | Set by / when | Read by |
|-------|------|---------------|---------|
| `query` | str | `_new_session` (start) | parse step (2) |
| `parsed` | dict | step 2 (LLM parse) → `{description, size, max_price}` | search (3) |
| `search_results` | list[dict] | step 3 (`search_listings` return) | branch check (3), select (4) |
| `selected_item` | dict \| None | step 4 (`search_results[0]`) | `suggest_outfit` (5), `create_fit_card` (6), final output |
| `wardrobe` | dict | `_new_session` (passed in) | `suggest_outfit` (5) |
| `outfit_suggestion` | str \| None | step 5 (`suggest_outfit` return) | `create_fit_card` (6), final output |
| `fit_card` | str \| None | step 6 (`create_fit_card` return) | final output |
| `error` | str \| None | step 3 (only when search returns `[]`) | caller / Gradio UI |

**Concrete hand-offs (no re-entry, no hardcoding):**
- `search_listings` returns a list → stored in `search_results` → its top element is copied to `selected_item`.
- `selected_item` (the exact same dict) is passed into **both** `suggest_outfit` and `create_fit_card` — the user never re-types the item.
- `suggest_outfit`'s return string is stored in `outfit_suggestion` and passed straight into `create_fit_card`.
- On the empty-search branch, only `error` is set; `selected_item`, `outfit_suggestion`, and `fit_card` remain `None`, which is how the caller knows the run stopped early.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No listings match the query | Returns `[]` (never raises). The planning loop sets `session["error"]` and **returns early without calling the LLM tools**. User sees a specific, actionable message naming what to loosen — e.g. *"No listings matched 'designer ballgown' in size XXS under $5. Try removing the size filter, raising your max price, or using broader keywords like 'dress'."* The outfit and fit-card panels stay blank. |
| suggest_outfit | Wardrobe is empty (`items == []`) | Tool detects the empty wardrobe and switches to a general-styling prompt, returning useful generic advice (the item's vibe + what kinds of pieces pair well) instead of crashing or returning `""`. |
| create_fit_card | Outfit string missing / empty / whitespace | Tool guards the empty input and returns a descriptive string — *"Can't make a fit card yet — no outfit was generated to caption."* — without calling the LLM or raising. |
| Planning loop (query parse) | LLM returns invalid / non-JSON | Falls back to `{description: <raw query>, size: None, max_price: None}` so search still runs on the raw keywords; a bad parse never crashes the run. |

**Secondary guard (both LLM tools):** every Groq call is wrapped so that an API exception or an empty response returns a safe, non-empty fallback string rather than propagating an error to the user.

---

## Architecture

```
User query + wardrobe choice            (Gradio: app.py → handle_query)
    │
    ▼
run_agent(query, wardrobe)
    │   session = _new_session()         ◄── single source of truth (STATE)
    │
    ├─►[2] LLM parse query  → session["parsed"] = {description, size, max_price}
    │         └ invalid JSON → fallback {description: query, size: None, max_price: None}
    │
    ├─►[3] search_listings(description, size, max_price) → session["search_results"]
    │         │
    │         ├─ results == []  ─► session["error"] = "No matches… loosen size/price"
    │         │                    return session  ──────────────► [STOP]
    │         │                    (suggest_outfit / create_fit_card NOT called;
    │         │                     selected_item, outfit_suggestion, fit_card stay None)
    │         │
    │         ▼ results = [item, …]
    ├─►[4] session["selected_item"] = search_results[0]
    │
    ├─►[5] suggest_outfit(selected_item, wardrobe) → session["outfit_suggestion"]
    │         └ wardrobe empty → general styling advice (fallback)
    │
    ├─►[6] create_fit_card(outfit_suggestion, selected_item) → session["fit_card"]
    │         └ empty outfit → descriptive error-message string
    │
    └─►[7] return session
    │
    ▼
Gradio panels:   🛍️ listing   |   👗 outfit   |   ✨ fit card
                 (error path: message in panel 1, panels 2 & 3 blank)
```

---

## AI Tool Plan

<!-- For each part of the implementation below, describe:
     - Which AI tool you plan to use (Claude, Copilot, ChatGPT, etc.)
     - What you'll give it as input (which sections of this planning.md, your agent diagram)
     - What you expect it to produce
     - How you'll verify the output matches your spec before moving on

     "I'll use AI to help me code" is not a plan.
     "I'll give Claude my Tool 1 spec (inputs, return value, failure mode) and ask it to implement
     search_listings() using load_listings() from the data loader — then test it against 3 queries
     before trusting it" is a plan. -->

**Milestone 3 — Individual tool implementations:**
- **Tool:** Claude (via Claude Code).
- **Input I give it:** the Tool 1 / Tool 2 / Tool 3 spec blocks above — one at a time — including the exact signature, the filtering/scoring or prompt logic, the return shape, and the failure mode, plus the listing/wardrobe field reference.
- **Expected output:** each function implemented directly in `tools.py`, matching the stub signature, using `load_listings()` for `search_listings` and the Groq client (`llama-3.3-70b-versatile`) for the two LLM tools.
- **How I verify before trusting it:** review each generated function against its spec — does `search_listings` filter by all three params, use smart size-token matching, apply the weighted score, and return `[]` on no match? Do the LLM tools handle the empty-wardrobe / empty-outfit cases? Then run `pytest tests/` (one test per failure mode) and run `create_fit_card` twice on the same input to confirm the output varies.

**Milestone 4 — Planning loop and state management:**
- **Tool:** Claude (via Claude Code).
- **Input I give it:** the **Planning Loop** + **State Management** sections and the **Architecture** diagram above.
- **Expected output:** `run_agent()` implementing the conditional-sequential flow — LLM parse (with JSON fallback), `search_listings`, the empty-results early-return branch, then `suggest_outfit` → `create_fit_card`, writing each result into the `session` dict; plus `handle_query()` in `app.py` mapping the session to the three output panels.
- **How I verify before trusting it:** confirm it branches on the `search_listings` result and does **not** call all three tools unconditionally; run `python agent.py` and check the happy path populates `selected_item` / `outfit_suggestion` / `fit_card`, while the no-results case sets `session["error"]` and leaves `fit_card` as `None`; print session fields to confirm state passes between tools without re-entry.

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Overview (in my own words):** FitFindr takes one natural-language thrifting request and runs it through three tools in sequence, carrying everything in a single session dict so nothing has to be re-entered. The user's query triggers `search_listings`, which filters the 40 mock listings by keyword relevance (against title, description, and style_tags), optional size, and optional max price; if there are matches, the top one becomes `selected_item` and flows into `suggest_outfit`, which proposes outfit combinations using the user's wardrobe — or general styling advice if the wardrobe is empty — and that result flows into `create_fit_card`, which writes a shareable caption. If `search_listings` returns an empty list, the agent stops there, writes a helpful "no matches — try loosening size/price" message to `session["error"]`, and never calls the downstream tools with empty input.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1 — init + parse.** `run_agent()` receives the query and the example wardrobe and builds a fresh `session`. The LLM parse step reads the query and returns `session["parsed"] = {"description": "vintage graphic tee", "size": None, "max_price": 30.0}`. (The "baggy jeans and chunky sneakers" part is conversational context about the wardrobe, not a search filter, so the parser leaves `size` as `None`.)

**Step 2 — search.** The loop calls `search_listings("vintage graphic tee", None, 30.0)`. Price filter keeps items ≤ $30; weighted keyword scoring on `{vintage, graphic, tee}` ranks the matches. Top result is **`lst_006` — "Graphic Tee — 2003 Tour Bootleg Style", $24, depop** (score ≈ 11: tags `graphic tee`/`vintage` + title/description hits), ahead of the faded band tee (`lst_033`, $19) and Y2K baby tee (`lst_002`, $18). Results are non-empty → no error branch. `session["selected_item"] = lst_006`.

**Step 3 — suggest outfit.** The loop calls `suggest_outfit(lst_006, example_wardrobe)`. The wardrobe is non-empty, so the LLM builds outfits around owned pieces and names them: *"Style the bootleg graphic tee with your **Baggy straight-leg jeans** and **Chunky white sneakers**, then layer your **Vintage black denim jacket** over the top for an easy 90s streetwear look. Add a thin silver chain (not in your closet) to finish."* Stored in `session["outfit_suggestion"]`.

**Step 4 — fit card.** The loop calls `create_fit_card(<that outfit string>, lst_006)`. The LLM returns a polished caption mentioning the item, price, and platform once each: *"90s grunge, under $25. This bootleg graphic tee ($24, Depop) was made for baggy denim and chunky sneakers, layered under a vintage black denim jacket for the perfect throwback fit. #thriftfind #90sstyle"* Stored in `session["fit_card"]`; `run_agent` returns the session.

**Final output to user:** The Gradio UI populates all three panels — 🛍️ the `lst_006` listing details (title, $24, good condition, Depop), 👗 the outfit idea naming their jeans/sneakers/jacket, and ✨ the fit-card caption. `session["error"]` is `None`. (On the deliberate no-results query — "designer ballgown size XXS under $5" — the user would instead see only the error message in panel 1 and two blank panels.)
