from unittest.mock import MagicMock

from backend.chatbot import (
    _load_sample_questions,
    _overlaps_range,
    _rank_texts,
    _resolve_target_event,
)


def test_chat_health_reports_ollama_and_question_corpus(client, monkeypatch):
    _load_sample_questions.cache_clear()
    monkeypatch.setattr(
        "backend.chatbot._load_sample_questions",
        lambda: [
            "What do I have today?",
            "Create a meeting tomorrow at 10 AM.",
        ],
    )
    monkeypatch.setattr(
        "backend.chatbot._load_sample_corpus",
        lambda: {
            "all": ["What do I have today?", "Create a meeting tomorrow at 10 AM."],
            "by_action": {
                "create_event": ["Create a meeting tomorrow at 10 AM."],
                "update_event": [],
                "delete_event": [],
            },
            "sources": ["sample.txt"],
        },
    )
    monkeypatch.setattr(
        "backend.chatbot._load_action_sample_questions",
        lambda: {
            "create_event": ["Create a meeting tomorrow at 10 AM."],
            "update_event": [],
            "delete_event": [],
        },
    )
    monkeypatch.setattr(
        "backend.chatbot.OllamaClient.ensure_ready",
        lambda self: {"models": [{"name": "llama3.1:8b"}]},
    )

    response = client.get("/chat/health")

    assert response.status_code == 200
    body = response.json()
    assert body["sample_questions_loaded"] == 2
    assert "llama3.1:8b" in body["models"]
    assert body["action_sample_counts"]["create_event"] == 1


def test_load_sample_questions_can_read_directory(tmp_path, monkeypatch):
    sample_dir = tmp_path / "rag_samples"
    sample_dir.mkdir()
    (sample_dir / "create_event_questions.txt").write_text(
        "1. Create a team sync tomorrow at 10 AM.\n",
        encoding="utf-8",
    )
    (sample_dir / "delete_event_questions.txt").write_text(
        "1. Delete my dentist appointment next Friday.\n",
        encoding="utf-8",
    )

    _load_sample_questions.cache_clear()
    monkeypatch.setattr("backend.chatbot.get_sample_questions_path", lambda: sample_dir)

    try:
        questions = _load_sample_questions()
    finally:
        _load_sample_questions.cache_clear()

    assert questions == [
        "Create a team sync tomorrow at 10 AM.",
        "Delete my dentist appointment next Friday.",
    ]


def test_chat_answer_flow_returns_response(client, monkeypatch):
    monkeypatch.setattr("backend.chatbot.get_tokens", lambda request: {"token": "fake"})
    monkeypatch.setattr("backend.chatbot.build_credentials", lambda tokens: MagicMock())
    monkeypatch.setattr(
        "backend.chatbot.list_calendars",
        lambda creds: [{"id": "primary", "name": "My Calendar", "color": "#4285F4"}],
    )
    monkeypatch.setattr(
        "backend.chatbot.fetch_all_events",
        lambda creds, calendar_ids=None, q=None, time_min=None, time_max=None, max_results=250: (
            [
                {
                    "id": "evt-1",
                    "calendarId": "primary",
                    "title": "Dentist appointment",
                    "start": {"dateTime": "2026-04-14T09:00:00+05:30"},
                    "end": {"dateTime": "2026-04-14T10:00:00+05:30"},
                    "description": "",
                    "location": "City Dental",
                    "attendees": [],
                }
            ],
            ["primary"],
        ),
    )
    monkeypatch.setattr(
        "backend.chatbot._load_sample_questions",
        lambda: ["What do I have today?"],
    )
    monkeypatch.setattr(
        "backend.chatbot.OllamaClient.chat_json",
        lambda self, system_prompt, user_prompt: {
            "action": "answer",
            "needs_clarification": False,
            "clarification_question": "",
            "calendar_id": "primary",
            "search_query": "dentist",
            "target_hint": "",
            "time_min": "2026-04-14T00:00:00+05:30",
            "time_max": "2026-04-14T23:59:59+05:30",
            "event": {},
            "updates": {},
        },
    )
    monkeypatch.setattr(
        "backend.chatbot._rank_texts",
        lambda query, texts, client, top_k: [(0, 0.9)],
    )
    monkeypatch.setattr(
        "backend.chatbot.OllamaClient.chat_text",
        lambda self, system_prompt, user_prompt: (
            "You have a dentist appointment today at 9:00 AM."
        ),
    )

    response = client.post(
        "/chat", json={"message": "What do I have today?", "history": []}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "answer"
    assert "dentist appointment" in body["answer"].lower()
    assert body["events"][0]["title"] == "Dentist appointment"


def test_chat_answer_handles_all_day_events_without_datetime_crash(client, monkeypatch):
    monkeypatch.setattr("backend.chatbot.get_tokens", lambda request: {"token": "fake"})
    monkeypatch.setattr("backend.chatbot.build_credentials", lambda tokens: MagicMock())
    monkeypatch.setattr(
        "backend.chatbot.list_calendars",
        lambda creds: [
            {
                "id": "primary",
                "name": "My Calendar",
                "color": "#4285F4",
                "primary": True,
            }
        ],
    )
    monkeypatch.setattr(
        "backend.chatbot.fetch_all_events",
        lambda creds, calendar_ids=None, q=None, time_min=None, time_max=None, max_results=250: (
            [
                {
                    "id": "holiday-1",
                    "calendarId": "primary",
                    "title": "Public Holiday",
                    "start": {"date": "2026-04-14"},
                    "end": {"date": "2026-04-15"},
                    "description": "",
                    "location": "",
                    "attendees": [],
                }
            ],
            ["primary"],
        ),
    )
    monkeypatch.setattr(
        "backend.chatbot._load_sample_questions", lambda: ["What do I have today?"]
    )
    monkeypatch.setattr(
        "backend.chatbot.OllamaClient.chat_json",
        lambda self, system_prompt, user_prompt: {
            "action": "answer",
            "needs_clarification": False,
            "clarification_question": "",
            "calendar_id": "primary",
            "search_query": "holiday",
            "target_hint": "",
            "time_min": "2026-04-14T00:00:00+05:30",
            "time_max": "2026-04-14T23:59:59+05:30",
            "event": {},
            "updates": {},
        },
    )
    monkeypatch.setattr(
        "backend.chatbot._rank_texts",
        lambda query, texts, client, top_k: [(0, 0.9)],
    )
    monkeypatch.setattr(
        "backend.chatbot.OllamaClient.chat_text",
        lambda self, system_prompt, user_prompt: (
            "You have a public holiday on April 14."
        ),
    )

    response = client.post(
        "/chat", json={"message": "Do I have anything today?", "history": []}
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "answer"


def test_chat_update_can_resolve_follow_up_from_history_events(client, monkeypatch):
    monkeypatch.setattr("backend.chatbot.get_tokens", lambda request: {"token": "fake"})
    monkeypatch.setattr("backend.chatbot.build_credentials", lambda tokens: MagicMock())
    monkeypatch.setattr(
        "backend.chatbot.list_calendars",
        lambda creds: [
            {
                "id": "primary",
                "name": "My Calendar",
                "color": "#4285F4",
                "primary": True,
            }
        ],
    )
    monkeypatch.setattr(
        "backend.chatbot.fetch_all_events",
        lambda creds, calendar_ids=None, q=None, time_min=None, time_max=None, max_results=250: (
            [],
            ["primary"],
        ),
    )
    monkeypatch.setattr(
        "backend.chatbot._load_sample_questions", lambda: ["Move my event to tomorrow."]
    )
    monkeypatch.setattr(
        "backend.chatbot.OllamaClient.chat_json",
        lambda self, system_prompt, user_prompt: {
            "action": "update_event",
            "needs_clarification": False,
            "clarification_question": "",
            "calendar_id": "primary",
            "search_query": "Sample title",
            "target_hint": "Sample title",
            "time_min": "",
            "time_max": "",
            "event": {},
            "updates": {
                "start": "2026-04-29T17:00:00+05:30",
                "end": "2026-04-29T19:00:00+05:30",
                "all_day": False,
            },
        },
    )
    monkeypatch.setattr(
        "backend.chatbot.update_event",
        lambda creds, calendar_id, event_id, body: {
            "id": event_id,
            "calendarId": calendar_id,
            "title": "Sample title",
            "start": {"dateTime": body["start"]["dateTime"]},
            "end": {"dateTime": body["end"]["dateTime"]},
        },
    )

    response = client.post(
        "/chat",
        json={
            "message": "Sample title",
            "history": [
                {
                    "role": "assistant",
                    "content": "Please clarify which one you mean.",
                    "events": [
                        {
                            "id": "evt-1",
                            "calendarId": "primary",
                            "title": "Sample title",
                            "start": {"dateTime": "2080-04-01T10:00:00+05:30"},
                            "end": {"dateTime": "2080-04-04T11:00:00+05:30"},
                            "description": "",
                            "location": "",
                            "attendees": [],
                        }
                    ],
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "action"
    assert body["events"][0]["title"] == "Sample title"


def test_chat_delete_does_not_delete_unrelated_event_when_title_does_not_match(
    client, monkeypatch
):
    monkeypatch.setattr("backend.chatbot.get_tokens", lambda request: {"token": "fake"})
    monkeypatch.setattr("backend.chatbot.build_credentials", lambda tokens: MagicMock())
    monkeypatch.setattr(
        "backend.chatbot.list_calendars",
        lambda creds: [
            {
                "id": "primary",
                "name": "My Calendar",
                "color": "#4285F4",
                "primary": True,
            }
        ],
    )
    monkeypatch.setattr(
        "backend.chatbot.fetch_all_events",
        lambda creds, calendar_ids=None, q=None, time_min=None, time_max=None, max_results=250: (
            [
                {
                    "id": "evt-1",
                    "calendarId": "primary",
                    "title": "Sample Public event",
                    "start": {"date": "2026-02-14"},
                    "end": {"date": "2026-02-15"},
                    "description": "",
                    "location": "",
                    "attendees": [],
                }
            ],
            ["primary"],
        ),
    )
    monkeypatch.setattr(
        "backend.chatbot._load_sample_questions", lambda: ["Delete my event"]
    )
    monkeypatch.setattr(
        "backend.chatbot.OllamaClient.chat_json",
        lambda self, system_prompt, user_prompt: {
            "action": "delete_event",
            "needs_clarification": False,
            "clarification_question": "",
            "calendar_id": "primary",
            "search_query": "Python Anaconda event",
            "target_hint": "Python Anaconda event",
            "time_min": "",
            "time_max": "",
            "event": {},
            "updates": {},
        },
    )

    response = client.post(
        "/chat",
        json={"message": "delete Python Anaconda event", "history": []},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "clarification"
    assert "could not identify a single matching event" in body["answer"].lower()


def test_rank_texts_uses_embedding_fallback_when_lexical_overlap_is_zero():
    texts = [f"filler text {index}" for index in range(99)] + ["dentist appointment"]

    class FakeClient:
        def embed_texts(self, requested_texts):
            embeddings = [[1.0, 0.0]]
            for text in requested_texts[1:]:
                embeddings.append(
                    [1.0, 0.0] if text == "dentist appointment" else [0.0, 1.0]
                )
            return embeddings

    ranked = _rank_texts("checkup", texts, FakeClient(), top_k=1)

    assert ranked == [(99, 1.0)]


def test_resolve_target_event_can_fall_back_to_semantic_match(monkeypatch):
    dentist_event = {
        "id": "evt-1",
        "calendarId": "primary",
        "title": "Dentist appointment",
        "start": {"dateTime": "2026-04-14T09:00:00+05:30"},
        "end": {"dateTime": "2026-04-14T10:00:00+05:30"},
    }
    lunch_event = {
        "id": "evt-2",
        "calendarId": "primary",
        "title": "Lunch with team",
        "start": {"dateTime": "2026-04-14T12:00:00+05:30"},
        "end": {"dateTime": "2026-04-14T13:00:00+05:30"},
    }
    monkeypatch.setattr(
        "backend.chatbot._rank_events",
        lambda query, events, calendar_lookup, client, top_k: [
            (dentist_event, 0.91),
            (lunch_event, 0.41),
        ],
    )

    matched_event, options = _resolve_target_event(
        "cancel my checkup",
        {"target_hint": "checkup", "search_query": "checkup"},
        [dentist_event, lunch_event],
        [{"id": "primary", "name": "My Calendar", "primary": True}],
        MagicMock(),
    )

    assert matched_event == dentist_event
    assert options == [dentist_event, lunch_event]


def test_overlaps_range_treats_all_day_end_date_as_exclusive():
    event = {
        "id": "holiday-1",
        "calendarId": "primary",
        "title": "Public Holiday",
        "start": {"date": "2026-04-14"},
        "end": {"date": "2026-04-15"},
    }

    assert (
        _overlaps_range(event, "2026-04-14T00:00:00+00:00", "2026-04-14T23:59:59+00:00")
        is True
    )
    assert (
        _overlaps_range(event, "2026-04-15T00:00:00+00:00", "2026-04-15T23:59:59+00:00")
        is False
    )


def test_chat_answer_defaults_to_all_calendars_when_planner_omits_calendar_id(
    client, monkeypatch
):
    captured = {}

    monkeypatch.setattr("backend.chatbot.get_tokens", lambda request: {"token": "fake"})
    monkeypatch.setattr("backend.chatbot.build_credentials", lambda tokens: MagicMock())
    monkeypatch.setattr(
        "backend.chatbot.list_calendars",
        lambda creds: [
            {"id": "primary", "name": "Personal", "primary": True},
            {"id": "work", "name": "Work", "primary": False},
        ],
    )

    def fake_fetch_all_events(
        creds, calendar_ids=None, q=None, time_min=None, time_max=None, max_results=250
    ):
        captured["calendar_ids"] = calendar_ids
        return ([], ["primary", "work"])

    monkeypatch.setattr("backend.chatbot.fetch_all_events", fake_fetch_all_events)
    monkeypatch.setattr(
        "backend.chatbot._load_sample_questions", lambda: ["What do I have today?"]
    )
    monkeypatch.setattr(
        "backend.chatbot.OllamaClient.chat_json",
        lambda self, system_prompt, user_prompt: {
            "action": "answer",
            "needs_clarification": False,
            "clarification_question": "",
            "calendar_id": "",
            "search_query": "today",
            "target_hint": "",
            "time_min": "2026-04-14T00:00:00+05:30",
            "time_max": "2026-04-14T23:59:59+05:30",
            "event": {},
            "updates": {},
        },
    )
    monkeypatch.setattr(
        "backend.chatbot._rank_texts", lambda query, texts, client, top_k: []
    )
    monkeypatch.setattr(
        "backend.chatbot.OllamaClient.chat_text",
        lambda self, system_prompt, user_prompt: "You have nothing scheduled.",
    )

    response = client.post(
        "/chat", json={"message": "What do I have today?", "history": []}
    )

    assert response.status_code == 200
    assert captured["calendar_ids"] is None


def test_chat_answer_does_not_fall_back_to_unrelated_events_when_time_filter_is_empty(
    client, monkeypatch
):
    monkeypatch.setattr("backend.chatbot.get_tokens", lambda request: {"token": "fake"})
    monkeypatch.setattr("backend.chatbot.build_credentials", lambda tokens: MagicMock())
    monkeypatch.setattr(
        "backend.chatbot.list_calendars",
        lambda creds: [{"id": "primary", "name": "My Calendar", "primary": True}],
    )
    monkeypatch.setattr(
        "backend.chatbot.fetch_all_events",
        lambda creds, calendar_ids=None, q=None, time_min=None, time_max=None, max_results=250: (
            [
                {
                    "id": "evt-1",
                    "calendarId": "primary",
                    "title": "Today event",
                    "start": {"dateTime": "2026-04-14T09:00:00+05:30"},
                    "end": {"dateTime": "2026-04-14T10:00:00+05:30"},
                    "description": "",
                    "location": "",
                    "attendees": [],
                }
            ],
            ["primary"],
        ),
    )
    monkeypatch.setattr(
        "backend.chatbot._load_sample_questions", lambda: ["What do I have tomorrow?"]
    )
    monkeypatch.setattr(
        "backend.chatbot.OllamaClient.chat_json",
        lambda self, system_prompt, user_prompt: {
            "action": "answer",
            "needs_clarification": False,
            "clarification_question": "",
            "calendar_id": "",
            "search_query": "tomorrow",
            "target_hint": "",
            "time_min": "2026-04-15T00:00:00+05:30",
            "time_max": "2026-04-15T23:59:59+05:30",
            "event": {},
            "updates": {},
        },
    )
    monkeypatch.setattr(
        "backend.chatbot._rank_texts", lambda query, texts, client, top_k: []
    )

    def fake_chat_text(self, system_prompt, user_prompt):
        assert "RELEVANT_EVENTS:\nnone" in user_prompt
        return "You do not have anything scheduled tomorrow."

    monkeypatch.setattr("backend.chatbot.OllamaClient.chat_text", fake_chat_text)

    response = client.post(
        "/chat", json={"message": "What do I have tomorrow?", "history": []}
    )

    assert response.status_code == 200
    assert response.json()["events"] == []
