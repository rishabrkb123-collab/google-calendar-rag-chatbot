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
        vecs = vs.embed(["hello", "world"])
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
