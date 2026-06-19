# FitFindr 🛍️

FitFindr is a **multi-tool AI agent for secondhand / thrift shopping**. You describe what you're
looking for in plain language, and the agent searches mock listings, figures out how a find fits
with your existing wardrobe, and writes a shareable outfit caption — orchestrating three tools in
sequence, carrying state between them, and handling failures gracefully at each step.

Built for CodePath AI201, Week 2 (Multi-Tool AI Agents). LLM: **Groq `llama-3.3-70b-versatile`**.

---

## What it does (example interaction)

**Query:** `vintage graphic tee under $30` · **Wardrobe:** Example

1. **`search_listings`** filters the 40 mock listings, ranks them by relevance, and the agent picks
   the top match → *Graphic Tee — 2003 Tour Bootleg Style, $24, Depop.*
2. **`suggest_outfit`** styles it using the user's owned pieces → *"Pair it with your Baggy
   straight-leg jeans and Chunky white sneakers, then layer your Vintage black denim jacket…"*
3. **`create_fit_card`** captions it → *"Just scored this bootleg graphic tee ($24, Depop) and I'm
   obsessed… #streetwearstyle"*

**Error path:** if `search_listings` returns nothing (e.g. `designer ballgown size XXS under $5`),
the agent stops and tells the user what to adjust — it **never** calls the styling tools on empty input.

---

## Setup

```bash
python -m venv .venv
# Windows (PowerShell):  .venv\Scripts\Activate.ps1
# Windows (Git Bash):    source .venv/Scripts/activate
# macOS / Linux:         source .venv/bin/activate

pip install -r requirements.txt
```

Create a `.env` in the project root (already gitignored — never commit it):

```
GROQ_API_KEY=your_key_here
```

A free key is available at [console.groq.com](https://console.groq.com).

## Run

```bash
python app.py        # Gradio web UI — open the printed URL (usually http://127.0.0.1:7860)
python agent.py      # CLI: runs a happy-path query + a deliberate no-results query
```

## Test

```bash
pytest tests/        # 6 isolation tests: search logic + each tool's failure mode
```

---

## Architecture

```
User query + wardrobe choice            (Gradio: app.py -> handle_query)
    |
    v
run_agent(query, wardrobe)
    |   session = _new_session()        <-- single source of truth (STATE)
    |
    |-> [2] LLM parse query  -> session["parsed"] = {description, size, max_price}
    |         (invalid JSON -> fallback: search on the raw query, no filters)
    |
    |-> [3] search_listings(description, size, max_price) -> session["search_results"]
    |         |
    |         |- results == []  -> session["error"] = "No matches... loosen size/price"
    |         |                    return session  ------------------> [STOP]
    |         |                    (suggest_outfit / create_fit_card NOT called)
    |         v results = [item, ...]
    |-> [4] session["selected_item"] = search_results[0]
    |-> [5] suggest_outfit(selected_item, wardrobe) -> session["outfit_suggestion"]
    |-> [6] create_fit_card(outfit_suggestion, selected_item) -> session["fit_card"]
    |-> [7] return session
    |
    v
Gradio panels:   listing  |  outfit  |  fit card     (error path: message in panel 1, others blank)
```

---

## Tool inventory

### `search_listings(description, size, max_price) -> list[dict]`
- **Inputs:** `description` (str) — item keywords; `size` (str | None) — optional size filter;
  `max_price` (float | None) — optional inclusive price ceiling.
- **Output:** `list[dict]` — full listing dicts (all 11 fields) ranked by relevance, best first;
  `[]` when nothing matches. **Never raises.**
- **Purpose:** filter + rank the 40 mock listings. Pure data logic — **no LLM call**.
- **How:** drop items over `max_price`; keep items whose size *token set* contains the requested
  size (`"S/M"` → `{S, M}`, so `"M"` matches `S/M`/`M/L` but not `US 7`/`One Size`); score by weighted
  keyword overlap (**style_tags ×2, title ×1, description ×1**); drop score-0; sort descending.

### `suggest_outfit(new_item, wardrobe) -> str`
- **Inputs:** `new_item` (dict) — the chosen listing; `wardrobe` (dict) — `{"items": [...]}`,
  possibly empty.
- **Output:** `str` — 1–2 outfit suggestions naming the user's owned pieces (with at most one flagged
  fill-in). If the wardrobe is empty → general styling advice instead.
- **Purpose:** LLM-generated styling (Groq, temp 0.7) anchored on the new item and the user's closet.

### `create_fit_card(outfit, new_item) -> str`
- **Inputs:** `outfit` (str) — the suggestion from `suggest_outfit`; `new_item` (dict) — the listing.
- **Output:** `str` — a short, shareable caption (polished/punchy voice, temp 1.0, varies per run),
  mentioning the item name, price, and platform once each. If `outfit` is empty → a descriptive error
  string.
- **Purpose:** LLM-generated OOTD caption for the find.

### Supporting functions
- `run_agent(query: str, wardrobe: dict) -> dict` — the planning loop (orchestrates the three tools).
- `_parse_query(query: str) -> dict` — LLM-based parser that extracts `{description, size, max_price}`.

---

## How the planning loop works

`run_agent()` runs a **conditional sequential** loop — it does **not** call all three tools every
time. The control flow:

1. Initialize a fresh `session` dict.
2. **Parse** the query with the LLM (temp 0) → `{description, size, max_price}`, stored in
   `session["parsed"]`. If the model returns invalid JSON, fall back to searching the raw query.
3. **Search** with those params → `session["search_results"]`.
   **🔀 The decision:** if the list is **empty**, write a helpful message to `session["error"]` and
   **`return` immediately** — `suggest_outfit` and `create_fit_card` are never reached.
4. Otherwise set `session["selected_item"] = search_results[0]`.
5. `suggest_outfit(selected_item, wardrobe)` → `session["outfit_suggestion"]`.
6. `create_fit_card(outfit_suggestion, selected_item)` → `session["fit_card"]`.
7. Return the session.

The agent's path therefore **changes based on what `search_listings` returns** — that early-exit
branch is what makes it a planning loop rather than a fixed pipeline.

---

## State management

A single `session` dict (created by `_new_session()`) is the one source of truth for an interaction.
Each step **writes** its output to a field; later steps **read** from those fields — no re-entry, no
hardcoded values. Data flows **tool → session → tool**.

| Field | Set by / when | Read by |
|-------|---------------|---------|
| `query` | start | parse step |
| `parsed` | step 2 (LLM parse) | search |
| `search_results` | step 3 (`search_listings`) | branch check, select |
| `selected_item` | step 4 (`search_results[0]`) | `suggest_outfit`, `create_fit_card`, UI |
| `wardrobe` | start (passed in) | `suggest_outfit` |
| `outfit_suggestion` | step 5 (`suggest_outfit`) | `create_fit_card`, UI |
| `fit_card` | step 6 (`create_fit_card`) | UI |
| `error` | step 3 (only if search is empty) | caller / UI |

**Verified live:** running `python agent.py` prints `selected_item id : lst_006`,
`outfit_suggestion: 912 chars`, `fit_card: present` on the happy path, and `None / None / None` on the
no-results path — proving the same item flows through all three tools, and that the downstream tools
never run when search comes back empty.

---

## Error handling (per tool, with examples from testing)

| Tool | Failure mode | Response | Tested example |
|------|--------------|----------|----------------|
| `search_listings` | No matches | Returns `[]` (never raises). The loop sets `session["error"]` and stops **before** the LLM tools. | `search_listings('designer ballgown', 'XXS', 5)` → `[]`; agent → *"No listings matched 'designer ballgown' in size XXS under $5. Try removing the size filter, raising your max price, or using broader keywords."* |
| `suggest_outfit` | Empty wardrobe | Switches to a general-styling prompt instead of crashing/returning `""`. | `suggest_outfit(item, get_empty_wardrobe())` → *"This graphic tee has a cool, edgy vibe… pair it with distressed denim jeans and black ankle boots…"* |
| `create_fit_card` | Empty / whitespace outfit | Returns a descriptive error string **without** calling the LLM. | `create_fit_card('', item)` → *"Can't make a fit card yet — no outfit was generated to caption."* |
| Planning loop (parse) | LLM returns invalid JSON | Falls back to `{description: raw query, size: None, max_price: None}` so search still runs. | — |

**Secondary guard:** every Groq call is wrapped in `try/except`; an API error or empty response
returns a safe, non-empty fallback string rather than propagating an exception to the user.

These three failure modes are also covered by the test suite (`pytest tests/` → 6 passed).

---

## Spec reflection

**One way the spec helped:** writing the exact size-matching strategy and scoring weights in
`planning.md` *before* coding made `search_listings` unambiguous to implement. Reasoning through the
messy `size` field on paper (`"S/M"`, `"US 8.5"`, `"One Size"`) is what surfaced the naive-substring
bug *before* writing code — a plain `"S" in size` check would have matched `"US 7"` and `"One Size"`.
Choosing "smart token matching" up front meant the implementation was basically transcription.

**One way the implementation diverged:** the spec left query parsing open ("regex, string splitting,
or ask the LLM"). I chose **LLM parsing**, which then needed pieces the one-line plan didn't spell
out — pulling the JSON object out of the model's reply (it sometimes wraps it in ```json fences),
coercing `max_price` to a float, and falling back to the raw query when parsing fails. So that step
ended up more defensive than the plan implied.

---

## AI usage

> *(Personal reflection — confirm these match your own recollection / voice before submitting.)*

1. **Implementing `search_listings`.** I gave the AI the Tool 1 spec block from `planning.md` (inputs,
   the weighted-scoring rule, the failure mode) and asked it to implement the function using
   `load_listings()`. I directed the **"smart token match"** size strategy over exact or loose
   substring matching specifically so `"M"` would match `"S/M"` but not `"US 7"`. Before trusting the
   output I checked it filtered by all three parameters and returned `[]` on no match, then verified
   it on real queries and with `pytest`.

2. **Implementing the planning loop.** I gave the AI the *Planning Loop* + *State Management* sections
   and the architecture diagram and asked for `run_agent()`. I reviewed that it **branched** on the
   empty-search result (returning early) and **wrote each result into the session dict** rather than
   calling all three tools unconditionally. I then verified state actually flowed by printing
   `session["selected_item"]` / `outfit_suggestion` / `fit_card` — `lst_006` on success,
   `None / None / None` on the no-results path.

3. **Choosing the query-parsing approach.** I directed the decision to use **LLM-based parsing** over
   regex, and reviewed/kept the JSON-extraction-and-fallback handling so a malformed model reply
   degrades to searching the raw query instead of crashing the agent.
