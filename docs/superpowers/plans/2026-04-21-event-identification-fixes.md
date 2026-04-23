# Event Identification Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 16 root causes preventing the chatbot from correctly identifying which calendar event/appointment the user is referring to.

**Architecture:** All backend fixes land in `backend/chatbot.py` (STOPWORDS, document representation, matching thresholds, time windows, pronoun resolution, search query normalization, history filtering). One frontend fix in `frontend/src/components/ChatPanel.jsx` (pending plan propagation). No new files needed.

**Tech Stack:** Python/FastAPI backend, React/Vite frontend, ChromaDB + sentence-transformers (all-MiniLM-L6-v2) for semantic ranking.

---

## File Map

| File | Changes |
|------|---------|
| `backend/chatbot.py` | STOPWORDS, `_event_to_document`, `_select_ranked_event`, `_parse_history`, `_resolve_calendar_id`, + inline fixes in `chat()` |
| `frontend/src/components/ChatPanel.jsx` | `lastPendingPlan` useMemo |

---

### Task 1: Expand STOPWORDS and add `_PRONOUN_RE` constant

Fixes #3 (noisy search_query tokens), #8 (generic words like "meeting" causing false matches).

**Files:**
- Modify: `backend/chatbot.py:48-74`

- [ ] **Step 1: Replace STOPWORDS and add `_PRONOUN_RE`**

Replace the entire `STOPWORDS` block (lines 48–74) with:

```python
STOPWORDS = {
    "a",
    "about",
    "an",
    "appointment",
    "at",
    "by",
    "call",
    "cancel",
    "change",
    "create",
    "daily",
    "delete",
    "edit",
    "event",
    "for",
    "from",
    "in",
    "lunch",
    "meeting",
    "modify",
    "move",
    "my",
    "of",
    "on",
    "one",
    "reminder",
    "remove",
    "reschedule",
    "schedule",
    "session",
    "shift",
    "standup",
    "sync",
    "the",
    "this",
    "to",
    "update",
    "weekly",
    "with",
}

# Compiled once at module load — used for deterministic pronoun resolution.
_PRONOUN_RE = re.compile(
    r"\b(it|this|that|the same one?|that one|the event|that event|this event)\b",
    re.IGNORECASE,
)
```

- [ ] **Step 2: Run existing tests to verify no regressions**

```bash
cd "D:/Agentic Google Calender - RAG vectors"
python -m pytest backend/ -x -q 2>&1 | tail -20
```

Expected: all tests pass (STOPWORDS is only used by `_meaningful_tokens` which existing tests cover indirectly).

- [ ] **Step 3: Commit**

```bash
git add backend/chatbot.py
git commit -m "fix: expand STOPWORDS and add _PRONOUN_RE for event disambiguation"
```

---

### Task 2: Improve `_event_to_document` representation

Fixes #10 (attendee display names), #15 (title/date prominence), #16 (description truncation).

**Files:**
- Modify: `backend/chatbot.py:160-192`

- [ ] **Step 1: Replace `_event_to_document`**

```python
def _event_to_document(event: dict, calendar_lookup: dict[str, dict]) -> str:
    calendar_name = calendar_lookup.get(event.get("calendarId"), {}).get(
        "name", event.get("calendarId", "primary")
    )
    start = (
        event.get("start", {}).get("dateTime")
        or event.get("start", {}).get("date")
        or ""
    )
    end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date") or ""
    # Prefer displayName so "meeting with John" matches the attendee name, not just the email.
    attendee_parts = []
    for attendee in event.get("attendees", []):
        name = attendee.get("displayName") or attendee.get("email", "").split("@")[0]
        if name:
            attendee_parts.append(name)
    attendee_text = ", ".join(attendee_parts)
    # Title and date lead — they are the strongest event identifiers.
    parts = [f"title {event.get('title') or '(No title)'}"]
    if start:
        parts.append(f"date {start[:10]}")
    parts.append(f"calendar {calendar_name}")
    if start:
        parts.append(f"start {start}")
    if end:
        parts.append(f"end {end}")
    location = event.get("location", "")
    if location:
        parts.append(f"location {location}")
    description = (event.get("description") or "").strip()
    if description:
        parts.append(f"description {description[:600]}")
    if attendee_text:
        parts.append(f"attendees {attendee_text}")
    return " | ".join(parts)
```

- [ ] **Step 2: Run tests**

```bash
python -m pytest backend/ -x -q 2>&1 | tail -20
```

- [ ] **Step 3: Commit**

```bash
git add backend/chatbot.py
git commit -m "fix: improve event document representation for better semantic matching"
```

---

### Task 3: Tighten `_select_ranked_event` threshold and add margin check

Fixes #9 (0.15 threshold too permissive, wrong events auto-selected when two candidates score closely).

**Files:**
- Modify: `backend/chatbot.py:585-599`

- [ ] **Step 1: Replace `_select_ranked_event`**

```python
def _select_ranked_event(
    query: str,
    events: list[dict],
    calendar_lookup: dict[str, dict],
) -> tuple[Optional[dict], list[dict]]:
    ranked = _rank_events(query, events, calendar_lookup, top_k=3)
    if not ranked:
        return None, []

    top_event, top_score = ranked[0]
    options = [event for event, _ in ranked]
    # Require a meaningful minimum score.
    if top_score < 0.25:
        return None, options
    # When the top two candidates score too closely, show options rather than
    # auto-selecting the marginal winner — the user should confirm.
    if len(ranked) > 1 and (top_score - ranked[1][1]) < 0.10:
        return None, options
    return top_event, options
```

- [ ] **Step 2: Run tests**

```bash
python -m pytest backend/ -x -q 2>&1 | tail -20
```

- [ ] **Step 3: Commit**

```bash
git add backend/chatbot.py
git commit -m "fix: raise similarity threshold to 0.25 and require confidence margin"
```

---

### Task 4: Extend history window and fix `_resolve_calendar_id` fallback

Fixes #13 (6-turn history too short for pronoun reference chains), #7 (unrecognized calendar ID passed as-is to API).

**Files:**
- Modify: `backend/chatbot.py:376-380` (history)
- Modify: `backend/chatbot.py:318-334` (calendar resolution)

- [ ] **Step 1: Change history from 6 to 10 turns**

In `_parse_history`, change:
```python
    trimmed = history[-6:]
```
to:
```python
    trimmed = history[-10:]
```

- [ ] **Step 2: Fix `_resolve_calendar_id` to fall back to `default_value`**

Replace the last line of `_resolve_calendar_id`:
```python
    return requested_value
```
with:
```python
    # No matching calendar found — fall back to the safe default (e.g. "all"
    # for mutations) rather than forwarding an unrecognised LLM-generated string.
    return default_value
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest backend/ -x -q 2>&1 | tail -20
```

- [ ] **Step 4: Commit**

```bash
git add backend/chatbot.py
git commit -m "fix: extend history to 10 turns and fix calendar fallback on unrecognised ID"
```

---

### Task 5: Pronoun resolution and `search_query` normalization in `chat()`

Fixes #4 (LLM-dependent pronoun resolution), #3 (search_query polluted with full user message).

These two blocks go into the `chat()` function, right after the `# ── End pending-plan override ──` comment (line 1000) and before `resolved_calendar_id = ...`.

**Files:**
- Modify: `backend/chatbot.py` — inside `chat()`, after line 1000

- [ ] **Step 1: Add pronoun resolution + search_query normalization after the pending-plan override block**

Insert after the line `# ── End pending-plan override ────────────────────────────────────────────────`:

```python
    # ── Deterministic pronoun resolution ────────────────────────────────────
    # If the user says "it", "this", "that", etc. and the LLM produced no
    # target_hint, substitute the most recent history event's title directly.
    if (
        action in {"update_event", "delete_event"}
        and not plan.get("target_hint")
        and _PRONOUN_RE.search(payload.message)
        and history_events
    ):
        _last_title = history_events[-1].get("title", "")
        if _last_title:
            plan["target_hint"] = _last_title
            plan["search_query"] = _last_title

    # ── Normalise search_query for mutations ─────────────────────────────────
    # The LLM sometimes sets search_query to the full user message, flooding
    # the lexical matcher with noise tokens. Enforce: search_query == target_hint.
    if action in {"update_event", "delete_event"} and plan.get("target_hint"):
        plan["search_query"] = plan["target_hint"]
    # ────────────────────────────────────────────────────────────────────────
```

- [ ] **Step 2: Run tests**

```bash
python -m pytest backend/ -x -q 2>&1 | tail -20
```

- [ ] **Step 3: Commit**

```bash
git add backend/chatbot.py
git commit -m "fix: add deterministic pronoun resolution and normalise search_query for mutations"
```

---

### Task 6: Widen mutation time windows and pass `target_hint` as API `q` param

Fixes #2 (wrong temporal resolution leaves events outside fetch window), #5 (60-day lookback too short), #6 (`q` not used for mutations).

**Files:**
- Modify: `backend/chatbot.py` — the fetch block and clarification prefetch block inside `chat()`

- [ ] **Step 1: Widen clarification prefetch window (90 → 180 days)**

Find (inside `needs_clarification` branch, ~line 1019):
```python
                    time_min=plan.get("time_min") or (_now - timedelta(days=90)).isoformat(),
```
Replace with:
```python
                    time_min=plan.get("time_min") or (_now - timedelta(days=180)).isoformat(),
```

- [ ] **Step 2: Replace the mutation time window block and add `q` parameter**

Find the existing block:
```python
    # For update/delete apply a default lookback so past events are reachable.
    _fetch_time_min = plan.get("time_min") or None
    _fetch_time_max = plan.get("time_max") or None
    if action in {"update_event", "delete_event"} and not _fetch_time_min:
        _now2 = datetime.now(UTC)
        _fetch_time_min = (_now2 - timedelta(days=60)).isoformat()

    try:
        candidate_events, scanned_calendar_ids = fetch_all_events(
            creds,
            calendar_ids=[resolved_calendar_id]
            if resolved_calendar_id and resolved_calendar_id != "all"
            else None,
            q=(plan.get("search_query") or None) if action == "answer" else None,
            time_min=_fetch_time_min,
            time_max=_fetch_time_max,
        )
    except HttpError as exc:
        translate_google_api_error(exc)
```

Replace with:
```python
    # For update/delete always search at least 180 days back so older events
    # are reachable, even when the LLM set a narrower window.
    _fetch_time_min = plan.get("time_min") or None
    _fetch_time_max = plan.get("time_max") or None
    if action in {"update_event", "delete_event"}:
        _now2 = datetime.now(UTC)
        _default_min = (_now2 - timedelta(days=180)).isoformat()
        _default_max = (_now2 + timedelta(days=365)).isoformat()
        # Use whichever start is earlier (wider window wins).
        if not _fetch_time_min or _fetch_time_min > _default_min:
            _fetch_time_min = _default_min
        if not _fetch_time_max:
            _fetch_time_max = _default_max

    # Pre-filter at the Google API level using target_hint for mutations so the
    # candidate pool stays small and ranking is more accurate.
    if action == "answer":
        _q_param = plan.get("search_query") or None
    elif action in {"update_event", "delete_event"} and plan.get("target_hint"):
        _q_param = plan.get("target_hint")
    else:
        _q_param = None

    try:
        candidate_events, scanned_calendar_ids = fetch_all_events(
            creds,
            calendar_ids=[resolved_calendar_id]
            if resolved_calendar_id and resolved_calendar_id != "all"
            else None,
            q=_q_param,
            time_min=_fetch_time_min,
            time_max=_fetch_time_max,
        )
    except HttpError as exc:
        translate_google_api_error(exc)
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest backend/ -x -q 2>&1 | tail -20
```

- [ ] **Step 4: Commit**

```bash
git add backend/chatbot.py
git commit -m "fix: widen mutation time windows to 180 days and pass target_hint as API q param"
```

---

### Task 7: Filter history events in mutation candidate pool

Fixes #11 (unrelated history events from previous conversation turns polluting the disambiguation pool).

**Files:**
- Modify: `backend/chatbot.py` — inside `update_event`/`delete_event` branch in `chat()`

- [ ] **Step 1: Replace the `all_candidates_pool` assignment**

Find (inside `if action in {"update_event", "delete_event"}:` branch, ~line 1177):
```python
        all_candidates_pool = _dedupe_events([*history_events, *candidate_events])
```
Replace with:
```python
        # Only include history events that share token overlap with the current
        # target hint so unrelated past events don't pollute the matching pool.
        _target_tokens = _meaningful_tokens(
            plan.get("target_hint") or plan.get("search_query") or ""
        )
        _relevant_history = (
            [
                e for e in history_events
                if _target_tokens & _meaningful_tokens(e.get("title", ""))
            ]
            if _target_tokens
            else history_events
        )
        all_candidates_pool = _dedupe_events([*_relevant_history, *candidate_events])
```

- [ ] **Step 2: Apply same filter in clarification prefetch pool**

Find (inside `needs_clarification` → `update_event`/`delete_event` prefetch, ~line 1025):
```python
                target_prefetch, _ = _resolve_target_event(
                    payload.message,
                    plan,
                    _dedupe_events([*history_events, *prefetch_candidates]),
                    calendars,
                )
```
Replace with:
```python
                _pf_target_tokens = _meaningful_tokens(
                    plan.get("target_hint") or plan.get("search_query") or ""
                )
                _pf_history = (
                    [
                        e for e in history_events
                        if _pf_target_tokens & _meaningful_tokens(e.get("title", ""))
                    ]
                    if _pf_target_tokens
                    else history_events
                )
                target_prefetch, _ = _resolve_target_event(
                    payload.message,
                    plan,
                    _dedupe_events([*_pf_history, *prefetch_candidates]),
                    calendars,
                )
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest backend/ -x -q 2>&1 | tail -20
```

- [ ] **Step 4: Commit**

```bash
git add backend/chatbot.py
git commit -m "fix: filter history events by token overlap to prevent pool pollution"
```

---

### Task 8: Fix frontend `lastPendingPlan` useMemo

Fixes #12 (pending plan dropped when last assistant turn is non-clarification, losing action context across multi-turn flows).

**Files:**
- Modify: `frontend/src/components/ChatPanel.jsx:74-82`

- [ ] **Step 1: Simplify `lastPendingPlan` useMemo**

Replace:
```js
  const lastPendingPlan = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i]
      if (m.role !== 'assistant') continue
      if ((m.mode === 'clarification' || m.mode === 'confirmation') && m.pendingPlan) return m.pendingPlan
      return null
    }
    return null
  }, [messages])
```
With:
```js
  // Return the pending_plan from the last assistant turn, regardless of mode.
  // The backend only uses it when the message is a genuine clarification reply.
  const lastPendingPlan = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'assistant') return messages[i].pendingPlan ?? null
    }
    return null
  }, [messages])
```

- [ ] **Step 2: Run frontend tests**

```bash
cd "D:/Agentic Google Calender - RAG vectors/frontend"
npm test -- --run 2>&1 | tail -20
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ChatPanel.jsx
git commit -m "fix: simplify lastPendingPlan to always read from last assistant turn"
```

---

## Post-Implementation Verification

After all tasks are complete, run the full test suite:

```bash
cd "D:/Agentic Google Calender - RAG vectors"
python -m pytest backend/ -q 2>&1 | tail -30
cd frontend && npm test -- --run 2>&1 | tail -20
```

All tests must pass before declaring the feature done.
