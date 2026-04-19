# RAG Vector DB Integration — Design Spec
**Date:** 2026-04-20  
**Status:** Approved

---

## Overview

Replace the current in-memory cosine-similarity ranking in `chatbot.py` with a proper vector database (ChromaDB) backed by real semantic embeddings (Sentence Transformers `all-MiniLM-L6-v2`). This affects only the retrieval/ranking layer — the LLM pipeline (Groq/Ollama), Google Calendar API integration, and all frontend code remain unchanged.

---

## Problem

The current approach has two weaknesses:

1. **Groq path uses fake embeddings.** `GroqClient.embed_texts()` produces bag-of-words TF vectors, not semantic embeddings. Queries like "team standup" won't match "daily sync" even though they mean the same thing.
2. **No persistence.** Sample questions (1,000+ entries) are re-embedded from scratch on every single chat request. This is wasteful and slow.

---

## Solution

Introduce a `VectorStore` class that:
- Uses `sentence-transformers` (`all-MiniLM-L6-v2`) for all embeddings — runs in-process, free, 384-dim semantic vectors
- Uses `chromadb` (embedded mode) for persistent ANN search — stored to disk at `backend/chroma_db/`
- Seeds the sample questions collection once at startup, reuses it across all requests
- Upserts per-request event documents and queries them immediately for ranking

---

## Architecture

```
chatbot.py (_rank_texts)
        │
        ▼
VectorStore (backend/vector_store.py)
  ├── SentenceTransformer("all-MiniLM-L6-v2")   ← embeddings
  └── chromadb.PersistentClient("backend/chroma_db/")
        ├── collection: "sample_questions"        ← seeded once, persisted
        └── collection: "events_{user_hash}"      ← upserted per request
```

---

## New File: `backend/vector_store.py`

Single class `VectorStore` with these responsibilities:

| Method | Description |
|---|---|
| `__init__()` | Load SentenceTransformer model, open ChromaDB persistent client |
| `seed_sample_questions(questions)` | Embed + store questions if collection is empty |
| `query_sample_questions(query, top_k)` | ANN search, return top-k question strings |
| `upsert_events(user_id, docs, ids)` | Delete old collection for user, store new event docs |
| `query_events(user_id, query, top_k)` | ANN search over event collection, return (index, score) pairs |

A module-level singleton is created at import time and reused across all requests:
```python
_vector_store: VectorStore | None = None

def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
```

---

## Changes to `backend/chatbot.py`

**Only two targeted changes:**

1. **`_rank_texts()` replaced** — instead of calling `client.embed_texts()` and computing cosine similarity in Python, route through `VectorStore`:
   - Sample question ranking → `VectorStore.query_sample_questions()`
   - Event document ranking → `VectorStore.upsert_events()` + `VectorStore.query_events()`

2. **Startup seeding** — call `get_vector_store().seed_sample_questions(questions)` when sample questions are loaded (can be done lazily on first chat request).

No changes to `_plan_chat_action`, `_answer_from_context`, `chat()` endpoint, or any action handling.

---

## Changes to `backend/config.py`

Add one config value:
```python
DEFAULT_CHROMA_DB_PATH = BACKEND_DIR / "chroma_db"

def get_chroma_db_path() -> Path:
    configured = os.getenv("CHROMA_DB_PATH", "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else PROJECT_ROOT / path
    return DEFAULT_CHROMA_DB_PATH
```

---

## Changes to `backend/requirements.txt`

```
chromadb==0.5.23
sentence-transformers==3.4.1
```

---

## Changes to `backend/.env.example`

```
# Optional: override ChromaDB storage path
# CHROMA_DB_PATH=backend/chroma_db
```

---

## Ollama Embedding Path

When Ollama is the active backend (`GROQ_API_KEY` not set), `OllamaClient.embed_texts()` currently handles embeddings directly. With this change, **all embedding goes through `VectorStore`** regardless of the chat backend. `OllamaClient.embed_texts()` is no longer called by `chatbot.py` — it can remain in the file for completeness but is effectively unused in the ranking pipeline.

---

## ChromaDB Collection Design

### `sample_questions`
- Populated once at startup (or first request)
- Checked via `collection.count()` — if > 0, skip seeding
- Documents: raw question strings
- IDs: `"q_{index}"` (stable across restarts)
- Metadata: `{"source": filename}`

### `events_{user_hash}`
- `user_hash` = first 12 chars of SHA-256 of the user's primary calendar ID
- Dropped and recreated on each request (events are live Google Calendar data)
- Documents: `_event_to_document()` string (same format as today)
- IDs: `"{calendarId}_{eventId}"`
- Metadata: `{"index": original_list_index}` — used to map results back to event objects

---

## Data Flow (per request)

```
1. User sends message
2. Groq plans the action (unchanged)
3. Google Calendar API returns candidate events (unchanged)
4. VectorStore.upsert_events(user_hash, event_docs, ids)
5. VectorStore.query_events(user_hash, query, top_k=15) → ranked indices
6. VectorStore.query_sample_questions(query, top_k=6) → similar questions
7. Groq generates final answer from ranked events + similar questions (unchanged)
```

---

## Startup Seeding Flow

```
FastAPI starts
    │
    ▼
first chat request hits _load_sample_questions()
    │
    ▼
get_vector_store().seed_sample_questions(questions)
    │
    ├─ collection.count() > 0? → skip (already seeded)
    └─ else: embed all questions with all-MiniLM → store in ChromaDB
             (one-time cost, ~2-5 seconds for 1,000 questions)
```

---

## `.gitignore` Addition

```
backend/chroma_db/
```

The ChromaDB files are machine-local and should not be committed.

---

## Testing Impact

Existing tests in `tests/backend/test_chatbot.py` mock `OllamaClient.embed_texts`. Those mocks will need updating to patch `VectorStore.query_sample_questions` and `VectorStore.query_events` instead. No other test files are affected.

---

## Out of Scope

- Background sync / caching of calendar events in ChromaDB (events remain live from Google API)
- Multi-user isolation beyond the collection naming convention above
- Switching the chat LLM — Groq/Ollama selection is unchanged
