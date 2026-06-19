# FitFindr 🛍️

FitFindr is a **multi-tool AI agent for secondhand / thrift shopping**. You describe what you're
looking for in plain language, and the agent searches mock listings, figures out how a find fits
with your existing wardrobe, and writes a shareable outfit caption — orchestrating three tools in
sequence, carrying state between them, and handling failures gracefully at each step.

Built for CodePath AI201, Week 2 (Multi-Tool AI Agents). LLM: **Groq `llama-3.3-70b-versatile`**.

---
**Video Demo: https://youtu.be/SaeSsHOAdDQ**

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

**In one sentence:** the "planning loop" is the agent's brain — a function called `run_agent()` that
decides *which* tool to use, *in what order*, and (most importantly) *when to stop*.

**What "conditional sequential" means, in plain English:**
- **Sequential** = it does things in a set order, one after another (search → style → caption).
- **Conditional** = it can change course partway through, depending on what happens. It is *not*
  locked into running every step no matter what.

**An everyday analogy.** Think of a barista making your order. They work step by step — but if they
reach for the oat milk and the carton is empty, they *stop* and say "sorry, we're out of oat milk,"
instead of blindly finishing a drink you can't have. Our agent behaves the same way: if the search
turns up nothing, it stops and tells you, instead of trying to style and caption an item that doesn't
exist.

**The steps, walked through one at a time:**

1. **Start fresh.** The agent creates an empty "notepad" (called the `session`) to keep track of
   everything that happens during this one request.
2. **Understand the request.** Your sentence — *"vintage graphic tee under $30"* — is just words.
   The agent asks the AI to pull out the useful pieces: *what* you want (`description`), what `size`,
   and your `max_price` limit. (If the AI ever hands back something garbled, there's a safety net:
   the agent just searches using your original sentence rather than giving up.)
3. **Search — and here is the one big decision. 🔀** The agent searches the listings with those
   details.
   - **If nothing matches:** it writes a friendly "couldn't find anything, here's what to try" note
     and **stops right here.** The styling and caption tools are *never even called.*
   - **If it finds matches:** it continues.
4. **Pick the best match** — the top-ranked listing — to work with.
5. **Style it.** The agent hands that item (plus your wardrobe) to the outfit tool, which suggests
   how to wear it.
6. **Caption it.** The agent hands that outfit to the caption tool, which writes the shareable post.
7. **Return everything** it collected on the notepad.

**Why this is the important part:** the agent's path *changes depending on what the search finds.* A
successful search runs all three tools; a dead-end search runs only one and stops. That ability to
*decide* — instead of robotically doing every step every time — is exactly what makes this a real
**planning loop** and not just a fixed to-do list.

---

## State management — how info is passed between tools

**The problem it solves.** The three tools are separate pieces of code — the search tool doesn't
automatically know anything about the caption tool. So how does the item found in step 1 reach the
caption written in step 6, *without you having to re-type it*? The answer is a shared **notepad.**

**The notepad is the `session`.** Think of it like a single **order ticket** at a restaurant: the
waiter writes your order on it, passes it to the kitchen, the cook adds notes, then it goes to the
plating station — *one* ticket, carried from person to person, each adding their part. Nobody ever
re-asks you what you ordered.

In FitFindr, every step **writes** its result onto the session, and every later step **reads** what
it needs from it. Information flows **tool → session → tool**:

> search writes down the tee it found → the styling tool reads that tee and writes down an outfit →
> the caption tool reads that outfit and writes the post.

Here is exactly what gets written onto the notepad, *when*, and *who reads it later*:

| Field (a labeled box on the notepad) | Written by / when | Read later by |
|-------|---------------|---------|
| `query` | at the start (your original sentence) | the parse step |
| `parsed` | step 2 (the AI pulls out description/size/price) | search |
| `search_results` | step 3 (search's list of matches) | the decision + the "pick best" step |
| `selected_item` | step 4 (the top match) | `suggest_outfit`, `create_fit_card`, the UI |
| `wardrobe` | at the start (passed in) | `suggest_outfit` |
| `outfit_suggestion` | step 5 (the outfit text) | `create_fit_card`, the UI |
| `fit_card` | step 6 (the caption text) | the UI |
| `error` | step 3 (only if search found nothing) | the caller / the UI |

**The key idea:** nothing is ever re-typed or hard-coded between steps. The tee that search found is
the *exact same tee* the caption talks about, because it rode along on the session the whole way.

**Proof you can see for yourself.** Running `python agent.py` prints the session at the end:
- On a **successful** query you get `selected_item id : lst_006`, `outfit_suggestion: 912 chars`,
  `fit_card: present` — every box filled in.
- On a **dead-end** query you get `None / None / None` — those boxes stay empty, because the agent
  stopped early and those tools never ran.

That's the state management, made visible.

---

## Error handling — failing gracefully instead of crashing

**What "crashing" means (for non-coders).** When a program hits something it didn't expect, it can
just *stop dead* and dump a scary wall of red text (programmers call it a "traceback"). That's a
crash — confusing and useless for the person using the app. **Graceful** handling is the opposite:
when something goes wrong, the program *catches* it and responds with a calm, helpful message — and
keeps working.

Every tool in FitFindr is built to fail *gracefully.* Here's each thing that can go wrong and what
the agent does **instead of crashing:**

| Tool | What can go wrong | What it does instead of crashing | Real example from testing |
|------|--------------|----------|----------------|
| `search_listings` | Nothing matches your search | Returns an empty list (not an error). The loop then writes a helpful message and stops **before** the AI tools. | `search_listings('designer ballgown', 'XXS', 5)` → `[]`; agent → *"No listings matched 'designer ballgown' in size XXS under $5. Try removing the size filter, raising your max price, or using broader keywords."* |
| `suggest_outfit` | You haven't entered a wardrobe yet | Gives **general** styling advice instead of choking on an empty closet. | `suggest_outfit(item, get_empty_wardrobe())` → *"This graphic tee has a cool, edgy vibe… pair it with distressed denim jeans and black ankle boots…"* |
| `create_fit_card` | There's no outfit to caption | Returns a clear "can't do that yet" message **without** even calling the AI. | `create_fit_card('', item)` → *"Can't make a fit card yet — no outfit was generated to caption."* |
| Planning loop (parse) | The AI returns garbled, unreadable data | Falls back to searching your original sentence, so the request still works. | — |

In plain terms:
- **Search finds nothing?** It returns an empty result (not an error), and the agent tells you what
  to change.
- **No wardrobe entered?** The stylist gives general advice instead of breaking on an empty closet.
- **No outfit to caption?** The caption tool returns a friendly message instead of failing.

**One more safety net:** every call to the AI is wrapped in a "try it, and if it fails, recover"
block. If the AI service hiccups or returns nothing, the tool hands back a safe backup message rather
than crashing the whole app. All three failure modes are also locked in by automated tests
(`pytest tests/` → 6 passed), so we know they keep working.

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
