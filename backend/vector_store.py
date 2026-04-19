"""Persistent vector store backed by ChromaDB + Sentence Transformers.

All embeddings use ``all-MiniLM-L6-v2`` (384-dim, normalised) regardless
of which LLM backend (Groq / Ollama) is active for chat.
"""
from __future__ import annotations

import re
import threading
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
        if not questions:
            return
        if self._questions_seeded:
            return
        # Re-check DB count in case another instance seeded concurrently.
        if self._questions_col.count() > 0:
            self._questions_seeded = True
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
        if not self._questions_seeded:
            return []
        count = self._questions_col.count()
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

        Note: scores are not bounded to [0, 1]. A small lexical-overlap bonus
        (0.05 * token_overlap) is added to the cosine score, so high-overlap
        queries can produce scores slightly above 1.0.
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
_instance_lock = threading.Lock()


def get_vector_store() -> VectorStore:
    """Return the process-wide VectorStore singleton (lazy-initialised)."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                from backend.config import get_chroma_db_path  # avoids circular import
                _instance = VectorStore(db_path=get_chroma_db_path())
    return _instance
