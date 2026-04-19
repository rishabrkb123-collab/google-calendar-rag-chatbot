# RAG Vector DB Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace in-memory bag-of-words/cosine ranking in `chatbot.py` with ChromaDB-backed semantic vector search using Sentence Transformers (`all-MiniLM-L6-v2`), giving the app real semantic embeddings for free with persistent storage for sample questions.

**Architecture:** A new `VectorStore` class in `backend/vector_store.py` wraps ChromaDB (disk-persisted at `backend/chroma_db/`) and a SentenceTransformer model. `chatbot.py`'s `_rank_texts` becomes a one-line wrapper over `VectorStore.rank_texts()`; sample-question calls switch to `VectorStore.query_sample_questions()` which uses ChromaDB's ANN search against a collection seeded once at startup. Calendar event ranking continues to embed per-request (events are live data from Google).

**Tech Stack:** `chromadb>=0.5.0`, `sentence-transformers>=2.7.0` (`all-MiniLM-L6-v2`, 384-dim, normalised vectors, ~90 MB first-run download), FastAPI backend (Python 3.12).

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| **Create** | `backend/vector_store.py` | VectorStore class + `get_vector_store()` singleton |
| **Create** | `tests/backend/test_vector_store.py` | Unit tests for VectorStore |
| **Modify** | `backend/requirements.txt` | Add chromadb, sentence-transformers |
| **Modify** | `backend/config.py` | Add `get_chroma_db_path()` |
| **Modify** | `backend/chatbot.py` | Replace `_cosine_similarity`/`_rank_texts` internals; drop `client` from ranking helpers; wire VectorStore |
| **Modify** | `tests/backend/test_chatbot.py` | Replace `_rank_texts` mocks with `get_vector_store` mocks; update signatures |
| **Modify** | `.gitignore` | Exclude `backend/chroma_db/` |

---

## Task 1: Install dependencies

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add packages to requirements.txt**

Replace the contents of `backend/requirements.txt` with:

```
fastapi==0.111.0
uvicorn[standard]==0.29.0
python-dotenv==1.0.1
google-auth==2.29.0
google-auth-oauthlib==1.2.0
google-api-python-client==2.127.0
starlette==0.37.2
itsdangerous==2.2.0
httpx==0.27.0
aiofiles==23.2.1
pytest==8.2.0
pytest-asyncio==0.23.6
chromadb>=0.5.0
sentence-transformers>=2.7.0
```

- [ ] **Step 2: Install into the venv**

```bash
cd "D:/Agentic Google Calender - RAG vectors"
backend/venv/Scripts/pip install chromadb "sentence-transformers>=2.7.0"
```

Expected: packages install successfully. `all-MiniLM-L6-v2` model weights (~90 MB) download automatically on first `SentenceTransformer(...)` call, not at install time.

- [ ] **Step 3: Verify imports work**

```bash
backend/venv/Scripts/python -c "import chromadb; from sentence_transformers import SentenceTransformer; print('OK')"
```

Expected output: `OK`

- [ ] **Step 4: Commit**

```bash
cd "D:/Agentic Google Calender - RAG vectors"
git add backend/requirements.txt
git commit -m "chore: add chromadb and sentence-transformers dependencies"
```

---

## Task 2: Add ChromaDB path config

**Files:**
- Modify: `backend/config.py`

- [ ] **Step 1: Add `DEFAULT_CHROMA_DB_PATH` and `get_chroma_db_path()` to config.py**

After the line `DEFAULT_ACTION_SAMPLE_QUESTIONS_DIR = PROJECT_ROOT / "rag_samples"` (line 18), add:

```python
DEFAULT_CHROMA_DB_PATH = BACKEND_DIR / "chroma_db"
```

After the `get_action_sample_questions_dir()` function (after line 135), add:

```python
def get_chroma_db_path() -> Path:
    configured = os.getenv("CHROMA_DB_PATH", "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else PROJECT_ROOT / path
    return DEFAULT_CHROMA_DB_PATH
```

- [ ] **Step 2: Add example env entry**

In `backend/.env.example`, append:

```
# Optional: override ChromaDB storage path (default: backend/chroma_db/)
# CHROMA_DB_PATH=backend/chroma_db
```

- [ ] **Step 3: Commit**

```bash
cd "D:/Agentic Google Calender - RAG vectors"
git add backend/config.py backend/.env.example
git commit -m "feat: add get_chroma_db_path() config helper"
```

---

## Task 3: Write failing VectorStore tests

**Files:**
- Create: `tests/backend/test_vector_store.py`

- [ ] **Step 1: Create the test file**

Create `tests/backend/test_vector_store.py`:

```python
"""Unit tests for VectorStore. All embedding calls are mocked for speed."""
import math
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.vector_store import VectorStore


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_vs(tmp_path: Path) -> VectorStore:
    """Return a VectorStore backed by a fresh temp directory."""
    return VectorStore(db_path=tmp_path / "chroma")


def _fake_embed(texts: list[str]) -> list[list[float]]:
    """
    Deterministic fake embeddings for testing.
    'dentist'/'dental'/'checkup' → [1, 0, 0]
    'football'/'sport'           → [0, 1, 0]
    everything else              → [0, 0, 1]
    All vectors are already unit-length.
    """
    dental_keywords = {"dentist", "dental", "checkup", "appointment"}
    sport_keywords = {"football", "sport", "match", "score"}
    result = []
    for text in texts:
        tokens = set(text.lower().split())
        if tokens & dental_keywords:
            result.append([1.0, 0.0, 0.0])
        elif tokens & sport_keywords:
            result.append([0.0, 1.0, 0.0])
        else:
            result.append([0.0, 0.0, 1.0])
    return result


# ── embed ─────────────────────────────────────────────────────────────────────

def test_embed_returns_one_vector_per_text(tmp_path):
    vs = _make_vs(tmp_path)
    with patch.object(vs, "embed", side_effect=_fake_embed):
        vecs = _fake_embed(["hello", "world"])
    assert len(vecs) == 2


def test_embed_vectors_are_unit_length(tmp_path):
    vs = _make_vs(tmp_path)
    # Use the real model for this one — verifies normalize_embeddings=True
    vecs = vs.embed(["hello world", "meeting at 3pm"])
    for vec in vecs:
        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 1e-4, f"Vector not unit-length: norm={norm}"


def test_embed_empty_input_returns_empty(tmp_path):
    vs = _make_vs(tmp_path)
    assert vs.embed([]) == []


# ── seed_sample_questions ─────────────────────────────────────────────────────

def test_seed_sample_questions_stores_all_questions(tmp_path):
    vs = _make_vs(tmp_path)
    questions = ["What meetings today?", "Delete my dentist appointment"]
    with patch.object(vs, "embed", side_effect=_fake_embed):
        vs.seed_sample_questions(questions)
    # After seeding, query returns something
    with patch.object(vs, "embed", side_effect=_fake_embed):
        results = vs.query_sample_questions("dentist", top_k=1)
    assert len(results) == 1


def test_seed_sample_questions_is_idempotent(tmp_path):
    vs = _make_vs(tmp_path)
    questions = ["What meetings today?", "Delete my dentist appointment"]
    with patch.object(vs, "embed", side_effect=_fake_embed):
        vs.seed_sample_questions(questions)
        vs.seed_sample_questions(questions)  # second call must not duplicate
    # Collection should have exactly 2 entries
    assert vs._questions_col.count() == 2


def test_seed_sample_questions_persists_across_instances(tmp_path):
    db_path = tmp_path / "chroma"
    vs1 = VectorStore(db_path=db_path)
    questions = ["What meetings today?", "Delete my dentist appointment"]
    with patch.object(vs1, "embed", side_effect=_fake_embed):
        vs1.seed_sample_questions(questions)

    # New VectorStore instance pointing at same DB — should already be seeded
    vs2 = VectorStore(db_path=db_path)
    assert vs2._questions_seeded is True
    assert vs2._questions_col.count() == 2


def test_seed_sample_questions_no_op_on_empty_list(tmp_path):
    vs = _make_vs(tmp_path)
    vs.seed_sample_questions([])
    assert vs._questions_col.count() == 0


# ── query_sample_questions ────────────────────────────────────────────────────

def test_query_sample_questions_returns_strings(tmp_path):
    vs = _make_vs(tmp_path)
    questions = ["dental checkup appointment", "football match score", "team meeting agenda"]
    with patch.object(vs, "embed", side_effect=_fake_embed):
        vs.seed_sample_questions(questions)
        results = vs.query_sample_questions("dentist visit", top_k=1)
    assert isinstance(results, list)
    assert all(isinstance(r, str) for r in results)


def test_query_sample_questions_most_relevant_first(tmp_path):
    vs = _make_vs(tmp_path)
    questions = ["dental checkup appointment", "football match score", "team meeting agenda"]
    with patch.object(vs, "embed", side_effect=_fake_embed):
        vs.seed_sample_questions(questions)
        results = vs.query_sample_questions("dentist", top_k=2)
    assert results[0] == "dental checkup appointment"


def test_query_sample_questions_returns_empty_when_not_seeded(tmp_path):
    vs = _make_vs(tmp_path)
    with patch.object(vs, "embed", side_effect=_fake_embed):
        results = vs.query_sample_questions("anything", top_k=5)
    assert results == []


def test_query_sample_questions_caps_at_collection_size(tmp_path):
    vs = _make_vs(tmp_path)
    questions = ["only one question"]
    with patch.object(vs, "embed", side_effect=_fake_embed):
        vs.seed_sample_questions(questions)
        results = vs.query_sample_questions("anything", top_k=10)
    assert len(results) == 1


# ── rank_texts ────────────────────────────────────────────────────────────────

def test_rank_texts_returns_top_k_results(tmp_path):
    vs = _make_vs(tmp_path)
    texts = ["dental checkup appointment", "football match score", "team meeting agenda"]
    with patch.object(vs, "embed", side_effect=_fake_embed):
        ranked = vs.rank_texts("dentist visit", texts, top_k=2)
    assert len(ranked) == 2


def test_rank_texts_most_similar_is_first(tmp_path):
    vs = _make_vs(tmp_path)
    texts = ["dental checkup appointment", "football match score", "team meeting agenda"]
    with patch.object(vs, "embed", side_effect=_fake_embed):
        ranked = vs.rank_texts("dentist visit", texts, top_k=1)
    assert ranked[0][0] == 0  # "dental checkup appointment" at index 0
    assert ranked[0][1] > 0.5


def test_rank_texts_returns_empty_for_empty_input(tmp_path):
    vs = _make_vs(tmp_path)
    assert vs.rank_texts("query", [], top_k=5) == []


def test_rank_texts_uses_semantic_fallback_when_no_lexical_overlap(tmp_path):
    """With zero token overlap, semantic similarity still finds the right match."""
    vs = _make_vs(tmp_path)
    # "checkup" has zero lexical overlap with "dental appointment" — but semantically close
    texts = [f"unrelated filler text {i}" for i in range(5)] + ["dental appointment checkup"]
    with patch.object(vs, "embed", side_effect=_fake_embed):
        ranked = vs.rank_texts("dentist", texts, top_k=1)
    assert ranked[0][0] == 5  # index 5 is the dental text


def test_rank_texts_caps_results_at_available_texts(tmp_path):
    vs = _make_vs(tmp_path)
    texts = ["only one"]
    with patch.object(vs, "embed", side_effect=_fake_embed):
        ranked = vs.rank_texts("query", texts, top_k=10)
    assert len(ranked) == 1
```

- [ ] **Step 2: Run tests — expect ImportError (module not created yet)**

```bash
cd "D:/Agentic Google Calender - RAG vectors"
backend/venv/Scripts/python -m pytest tests/backend/test_vector_store.py -v 2>&1 | head -30
```

Expected: `ImportError: cannot import name 'VectorStore' from 'backend.vector_store'` (or `ModuleNotFoundError`). If it says anything else, investigate before continuing.

---

## Task 4: Implement VectorStore

**Files:**
- Create: `backend/vector_store.py`

- [ ] **Step 1: Create `backend/vector_store.py`**

```python
"""Persistent vector store backed by ChromaDB + Sentence Transformers.

All embeddings use ``all-MiniLM-L6-v2`` (384-dim, normalised) regardless
of which LLM backend (Groq / Ollama) is active for chat.
"""
from __future__ import annotations

import re
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer


class VectorStore:
    """Semantic search over calendar events and sample questions."""

    _MODEL_NAME = "all-MiniLM-L6-v2"

    def __init__(self, db_path: Path) -> None:
        db_path.mkdir(parents=True, exist_ok=True)
        self._model = SentenceTransformer(self._MODEL_NAME)
        self._chroma = chromadb.PersistentClient(path=str(db_path))
        self._questions_col = self._chroma.get_or_create_collection(
            "sample_questions",
            metadata={"hnsw:space": "cosine"},
        )
        # Skip seeding if the collection already has data from a previous run.
        self._questions_seeded: bool = self._questions_col.count() > 0

    # ── Embedding ─────────────────────────────────────────────────────────────

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return a unit-length 384-dim vector for each text."""
        if not texts:
            return []
        return self._model.encode(texts, normalize_embeddings=True).tolist()

    # ── Sample questions (persistent ChromaDB collection) ─────────────────────

    def seed_sample_questions(self, questions: list[str]) -> None:
        """Embed and store questions. No-op if already seeded or list is empty."""
        if self._questions_seeded or not questions:
            return
        embeddings = self.embed(questions)
        self._questions_col.add(
            documents=questions,
            embeddings=embeddings,
            ids=[f"q_{i}" for i in range(len(questions))],
        )
        self._questions_seeded = True

    def query_sample_questions(self, query: str, top_k: int) -> list[str]:
        """Return the top-k sample questions most semantically similar to query."""
        count = self._questions_col.count()
        if count == 0:
            return []
        k = min(top_k, count)
        query_emb = self.embed([query])[0]
        results = self._questions_col.query(
            query_embeddings=[query_emb],
            n_results=k,
        )
        return results["documents"][0] if results["documents"] else []

    # ── Ephemeral text ranking (used for calendar events) ─────────────────────

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", text.lower()))

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        return dot / (na * nb) if na and nb else 0.0

    def rank_texts(
        self, query: str, texts: list[str], top_k: int
    ) -> list[tuple[int, float]]:
        """Rank *texts* by semantic similarity to *query*.

        Returns a list of ``(original_index, score)`` pairs, highest score first,
        capped at *top_k*.  On large corpora a lexical pre-filter shortlists
        candidates before embedding to keep latency low.
        """
        if not texts:
            return []

        # Lexical pre-filter: score every text by token overlap with the query.
        query_tokens = self._tokenize(query)
        lexical_scores: list[tuple[int, float]] = []
        for i, text in enumerate(texts):
            overlap = len(query_tokens & self._tokenize(text))
            bonus = 0.25 if query.lower() in text.lower() else 0.0
            lexical_scores.append((i, overlap + bonus))
        lexical_scores.sort(key=lambda x: x[1], reverse=True)

        # Only apply the shortlist on large corpora with at least one lexical hit.
        shortlist_size = max(top_k * 6, 12)
        has_lexical = any(s > 0 for _, s in lexical_scores)
        if len(texts) <= max(top_k * 20, 80) or not has_lexical:
            candidate_indices = list(range(len(texts)))
        else:
            candidate_indices = [i for i, _ in lexical_scores[:shortlist_size]]

        candidate_texts = [texts[i] for i in candidate_indices]
        embeddings = self.embed([query, *candidate_texts])
        query_emb = embeddings[0]
        lex_lookup = dict(lexical_scores)

        ranked: list[tuple[int, float]] = []
        for i, emb in zip(candidate_indices, embeddings[1:]):
            score = self._cosine(query_emb, emb) + lex_lookup.get(i, 0.0) * 0.05
            ranked.append((i, score))

        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked[:top_k]


# ── Module-level singleton ────────────────────────────────────────────────────

_instance: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """Return the process-wide VectorStore singleton (lazy-initialised)."""
    global _instance
    if _instance is None:
        from backend.config import get_chroma_db_path  # local import avoids circular
        _instance = VectorStore(db_path=get_chroma_db_path())
    return _instance
```

- [ ] **Step 2: Run VectorStore tests — expect most to pass**

```bash
cd "D:/Agentic Google Calender - RAG vectors"
backend/venv/Scripts/python -m pytest tests/backend/test_vector_store.py -v
```

Expected: all tests **PASS**. The `test_embed_vectors_are_unit_length` test uses the real model (downloads once on first run — allow up to 2 minutes). If any test fails, fix before continuing.

- [ ] **Step 3: Commit**

```bash
cd "D:/Agentic Google Calender - RAG vectors"
git add backend/vector_store.py tests/backend/test_vector_store.py
git commit -m "feat: add VectorStore with ChromaDB + Sentence Transformers"
```

---

## Task 5: Refactor chatbot.py

**Files:**
- Modify: `backend/chatbot.py`

The changes are surgical — no logic changes, only wiring VectorStore in place of the old in-process embedding calls.

- [ ] **Step 1: Add VectorStore import**

At the top of `backend/chatbot.py`, after the existing imports, add:

```python
from backend.vector_store import get_vector_store
```

Also add `Any` to the `typing` import (it's already there via `from typing import Any, Optional`).

- [ ] **Step 2: Remove `_cosine_similarity` (moved to VectorStore)**

Delete the `_cosine_similarity` function (lines 100–108):

```python
def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)
```

Also remove `import math` from the top (line 1) since it is no longer used.

- [ ] **Step 3: Replace `_rank_texts` body with a one-line wrapper**

Replace the entire `_rank_texts` function body (lines 310–345) with:

```python
def _rank_texts(
    query: str, texts: list[str], client: Any, top_k: int
) -> list[tuple[int, float]]:
    """Thin wrapper over VectorStore.rank_texts. ``client`` is ignored."""
    return get_vector_store().rank_texts(query, texts, top_k)
```

- [ ] **Step 4: Update `_rank_events` — drop `client` parameter**

Replace the `_rank_events` function:

```python
# OLD
def _rank_events(
    query: str,
    events: list[dict],
    calendar_lookup: dict[str, dict],
    client: OllamaClient,
    top_k: int,
) -> list[tuple[dict, float]]:
    if not events:
        return []
    documents = [_event_to_document(event, calendar_lookup) for event in events]
    ranked_indices = _rank_texts(query, documents, client, top_k=top_k)
    return [(events[index], score) for index, score in ranked_indices]
```

```python
# NEW
def _rank_events(
    query: str,
    events: list[dict],
    calendar_lookup: dict[str, dict],
    top_k: int,
) -> list[tuple[dict, float]]:
    if not events:
        return []
    documents = [_event_to_document(event, calendar_lookup) for event in events]
    ranked_indices = _rank_texts(query, documents, None, top_k=top_k)
    return [(events[index], score) for index, score in ranked_indices]
```

- [ ] **Step 5: Update `_select_ranked_event` — drop `client` parameter**

```python
# OLD
def _select_ranked_event(
    query: str,
    events: list[dict],
    calendar_lookup: dict[str, dict],
    client: OllamaClient,
) -> tuple[Optional[dict], list[dict]]:
    ranked = _rank_events(query, events, calendar_lookup, client, top_k=3)
    if not ranked:
        return None, []
    top_event, top_score = ranked[0]
    options = [event for event, _ in ranked]
    if top_score < 0.15:
        return None, options
    return top_event, options
```

```python
# NEW
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
    if top_score < 0.15:
        return None, options
    return top_event, options
```

- [ ] **Step 6: Update `_resolve_target_event` — drop `client` parameter and update internal calls**

```python
# OLD signature
def _resolve_target_event(
    request_message: str,
    plan: dict[str, Any],
    events: list[dict],
    calendars: list[dict],
    client: OllamaClient,
) -> tuple[Optional[dict], list[dict]]:
```

```python
# NEW signature
def _resolve_target_event(
    request_message: str,
    plan: dict[str, Any],
    events: list[dict],
    calendars: list[dict],
) -> tuple[Optional[dict], list[dict]]:
```

Inside `_resolve_target_event`, update every call that passes `client`:

Find and replace:
```python
matched_event, ranked_options = _select_ranked_event(
    query, strongest_matches, calendar_lookup, client
)
if matched_event:
    return matched_event, strongest_matches
if ranked_options:
    return None, ranked_options
```
With:
```python
matched_event, ranked_options = _select_ranked_event(
    query, strongest_matches, calendar_lookup
)
if matched_event:
    return matched_event, strongest_matches
if ranked_options:
    return None, ranked_options
```

And the final return line:
```python
# OLD
return _select_ranked_event(query, events, calendar_lookup, client)
# NEW
return _select_ranked_event(query, events, calendar_lookup)
```

- [ ] **Step 7: Update `_plan_chat_action` — use VectorStore for sample questions**

In `_plan_chat_action`, replace these lines (the two `_rank_texts` calls for sample/action questions):

```python
# OLD
ranked_questions = (
    _rank_texts(request_message, sample_questions, client, top_k=6)
    if sample_questions
    else []
)
similar_questions = [sample_questions[index] for index, _ in ranked_questions]
ranked_action_samples = (
    _rank_texts(request_message, action_samples, client, top_k=6)
    if action_samples
    else []
)
similar_action_samples = [
    action_samples[index] for index, _ in ranked_action_samples
]
```

```python
# NEW
vs = get_vector_store()
vs.seed_sample_questions(sample_questions)
similar_questions = vs.query_sample_questions(request_message, top_k=6) if sample_questions else []
similar_action_samples = (
    [action_samples[i] for i, _ in vs.rank_texts(request_message, action_samples, top_k=6)]
    if action_samples
    else []
)
```

- [ ] **Step 8: Update `chat()` answer block — use VectorStore for sample questions**

In the `chat()` endpoint, inside the `if action == "answer":` block, replace:

```python
# OLD
ranked_questions = (
    _rank_texts(payload.message, sample_questions, client, top_k=6)
    if sample_questions
    else []
)
relevant_questions = [
    sample_questions[index] for index, _ in ranked_questions
]
```

```python
# NEW
vs = get_vector_store()
relevant_questions = vs.query_sample_questions(payload.message, top_k=6) if sample_questions else []
```

- [ ] **Step 9: Drop `client` from `_rank_events` call in `chat()` answer block**

Find in `chat()`:

```python
relevant_events = [
    event
    for event, _ in _rank_events(
        payload.message,
        filtered_events,
        calendar_lookup,
        client,
        top_k=15,
    )
]
```

Replace with:

```python
relevant_events = [
    event
    for event, _ in _rank_events(
        payload.message,
        filtered_events,
        calendar_lookup,
        top_k=15,
    )
]
```

- [ ] **Step 10: Drop `client` from the two `_resolve_target_event` call sites in `chat()`**

Find (in the clarification prefetch path, inside `if plan.get("needs_clarification"):`):

```python
target_prefetch, _ = _resolve_target_event(
    payload.message,
    plan,
    _dedupe_events([*history_events, *prefetch_candidates]),
    calendars,
    client,
)
```

Replace with:

```python
target_prefetch, _ = _resolve_target_event(
    payload.message,
    plan,
    _dedupe_events([*history_events, *prefetch_candidates]),
    calendars,
)
```

Find (in the update/delete path):

```python
target_event, options = _resolve_target_event(
    payload.message, plan, filtered_events, calendars, client
)
```

Replace with:

```python
target_event, options = _resolve_target_event(
    payload.message, plan, filtered_events, calendars
)
```

- [ ] **Step 11: Verify the backend starts without errors**

```bash
cd "D:/Agentic Google Calender - RAG vectors"
backend/venv/Scripts/python -c "from backend.chatbot import router; print('chatbot OK')"
```

Expected: `chatbot OK`

- [ ] **Step 12: Commit**

```bash
cd "D:/Agentic Google Calender - RAG vectors"
git add backend/chatbot.py
git commit -m "refactor: wire VectorStore into chatbot ranking pipeline"
```

---

## Task 6: Update test_chatbot.py

**Files:**
- Modify: `tests/backend/test_chatbot.py`

- [ ] **Step 1: Update the import block at the top of test_chatbot.py**

`MagicMock` is already imported at the top. Only change needed: remove `_rank_texts` from the chatbot import.

```python
# OLD
from backend.chatbot import (
    _load_sample_questions,
    _overlaps_range,
    _rank_texts,
    _resolve_target_event,
)
```

```python
# NEW
from backend.chatbot import (
    _load_sample_questions,
    _overlaps_range,
    _resolve_target_event,
)
```

- [ ] **Step 2: Delete `test_rank_texts_uses_embedding_fallback_when_lexical_overlap_is_zero`**

Remove the entire test (lines 364–378). It tested the old `_rank_texts` with a `FakeClient`; the equivalent test now lives in `test_vector_store.py` as `test_rank_texts_uses_semantic_fallback_when_no_lexical_overlap`.

- [ ] **Step 3: Update `test_chat_answer_flow_returns_response`**

Replace:

```python
monkeypatch.setattr(
    "backend.chatbot._rank_texts",
    lambda query, texts, client, top_k: [(0, 0.9)],
)
```

With a `get_vector_store` mock that covers both event ranking and sample-question lookup:

```python
mock_vs = MagicMock()
mock_vs.rank_texts.return_value = [(0, 0.9)]
mock_vs.query_sample_questions.return_value = ["What do I have today?"]
mock_vs.seed_sample_questions.return_value = None
monkeypatch.setattr("backend.chatbot.get_vector_store", lambda: mock_vs)
```

- [ ] **Step 4: Update `test_chat_answer_handles_all_day_events_without_datetime_crash`**

Replace:

```python
monkeypatch.setattr(
    "backend.chatbot._rank_texts",
    lambda query, texts, client, top_k: [(0, 0.9)],
)
```

With:

```python
mock_vs = MagicMock()
mock_vs.rank_texts.return_value = [(0, 0.9)]
mock_vs.query_sample_questions.return_value = ["What do I have today?"]
mock_vs.seed_sample_questions.return_value = None
monkeypatch.setattr("backend.chatbot.get_vector_store", lambda: mock_vs)
```

- [ ] **Step 5: Update `test_chat_answer_defaults_to_all_calendars_when_planner_omits_calendar_id`**

Replace:

```python
monkeypatch.setattr(
    "backend.chatbot._rank_texts", lambda query, texts, client, top_k: []
)
```

With:

```python
mock_vs = MagicMock()
mock_vs.rank_texts.return_value = []
mock_vs.query_sample_questions.return_value = []
mock_vs.seed_sample_questions.return_value = None
monkeypatch.setattr("backend.chatbot.get_vector_store", lambda: mock_vs)
```

- [ ] **Step 6: Update `test_chat_answer_does_not_fall_back_to_unrelated_events_when_time_filter_is_empty`**

Replace:

```python
monkeypatch.setattr(
    "backend.chatbot._rank_texts", lambda query, texts, client, top_k: []
)
```

With:

```python
mock_vs = MagicMock()
mock_vs.rank_texts.return_value = []
mock_vs.query_sample_questions.return_value = []
mock_vs.seed_sample_questions.return_value = None
monkeypatch.setattr("backend.chatbot.get_vector_store", lambda: mock_vs)
```

- [ ] **Step 7: Update `test_resolve_target_event_can_fall_back_to_semantic_match`**

Two changes:

1. Update `_rank_events` mock lambda to drop `client`:

```python
# OLD
monkeypatch.setattr(
    "backend.chatbot._rank_events",
    lambda query, events, calendar_lookup, client, top_k: [
        (dentist_event, 0.91),
        (lunch_event, 0.41),
    ],
)
```

```python
# NEW
monkeypatch.setattr(
    "backend.chatbot._rank_events",
    lambda query, events, calendar_lookup, top_k: [
        (dentist_event, 0.91),
        (lunch_event, 0.41),
    ],
)
```

2. Remove the `MagicMock()` client argument from the `_resolve_target_event` call:

```python
# OLD
matched_event, options = _resolve_target_event(
    "cancel my checkup",
    {"target_hint": "checkup", "search_query": "checkup"},
    [dentist_event, lunch_event],
    [{"id": "primary", "name": "My Calendar", "primary": True}],
    MagicMock(),
)
```

```python
# NEW
matched_event, options = _resolve_target_event(
    "cancel my checkup",
    {"target_hint": "checkup", "search_query": "checkup"},
    [dentist_event, lunch_event],
    [{"id": "primary", "name": "My Calendar", "primary": True}],
)
```

- [ ] **Step 8: Run the full test suite**

```bash
cd "D:/Agentic Google Calender - RAG vectors"
backend/venv/Scripts/python -m pytest tests/ -v
```

Expected: **all tests PASS**. If any test fails, read the error and fix before continuing.

- [ ] **Step 9: Commit**

```bash
cd "D:/Agentic Google Calender - RAG vectors"
git add tests/backend/test_chatbot.py
git commit -m "test: update chatbot tests to use get_vector_store mock"
```

---

## Task 7: Update .gitignore and documentation

**Files:**
- Modify: `.gitignore`
- Modify: `PROJECT_DOCUMENTATION.md`

- [ ] **Step 1: Add chroma_db to .gitignore**

Append to `.gitignore`:

```
# ChromaDB on-disk vector store (machine-local, not committed)
backend/chroma_db/
```

- [ ] **Step 2: Update PROJECT_DOCUMENTATION.md — embedding/RAG section**

Read `PROJECT_DOCUMENTATION.md` first, then find the section describing the LLM/embedding stack and replace the old description with:

```
## Embeddings & Vector Search

**Model:** `all-MiniLM-L6-v2` (Sentence Transformers) — runs in-process, no API key required, 384-dimensional normalised vectors.

**Vector DB:** ChromaDB (embedded, disk-persisted at `backend/chroma_db/`).

**Sample questions corpus** (`google_calendar_rag_1000_questions.txt` + `rag_samples/`):
Embedded once at first startup and stored in the `sample_questions` ChromaDB collection.
Subsequent requests query via ANN search — no re-embedding.

**Calendar event ranking:**
Event documents are embedded per-request (events are live from Google Calendar API) using the same model. Cosine similarity is computed in-process; no ChromaDB collection is written for events.

**Why all-MiniLM-L6-v2:**
Free, offline-capable, ~90 MB one-time download. Produces real semantic vectors — "team standup" and "daily sync" score as similar, unlike the previous bag-of-words approach used by the Groq client.
```

- [ ] **Step 3: Final commit**

```bash
cd "D:/Agentic Google Calender - RAG vectors"
git add .gitignore PROJECT_DOCUMENTATION.md
git commit -m "docs: update gitignore and documentation for vector DB integration"
```

---

## Spec Coverage Check

| Spec section | Covered by task |
|---|---|
| `VectorStore` class with all 5 methods | Task 4 |
| `get_vector_store()` singleton | Task 4 |
| `get_chroma_db_path()` config | Task 2 |
| `chromadb`, `sentence-transformers` deps | Task 1 |
| `_rank_texts` wrapper | Task 5 step 3 |
| `_rank_events` drops `client` | Task 5 step 4 |
| Sample questions seeded once | Task 5 steps 7–8 |
| `backend/chroma_db/` in `.gitignore` | Task 7 |
| Tests updated | Task 6 |
| `.env.example` updated | Task 2 |
