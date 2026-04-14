import math
import re
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.calendar_api import (
    build_credentials,
    create_event,
    delete_event,
    fetch_all_events,
    list_calendars,
    translate_google_api_error,
    update_event,
)
from backend.config import (
    DEFAULT_SAMPLE_QUESTIONS_FILE,
    get_action_sample_questions_dir,
    get_ollama_config,
    get_sample_questions_path,
)
from backend.ollama_client import OllamaClient, OllamaClientError
from backend.session import get_tokens
from googleapiclient.errors import HttpError


router = APIRouter(prefix="/chat")

STOPWORDS = {
    "a",
    "an",
    "at",
    "by",
    "change",
    "create",
    "delete",
    "edit",
    "event",
    "for",
    "from",
    "in",
    "modify",
    "move",
    "my",
    "one",
    "of",
    "on",
    "remove",
    "reschedule",
    "shift",
    "the",
    "this",
    "to",
    "update",
}

ACTION_SAMPLE_GROUPS = ("create_event", "update_event", "delete_event")


class ChatTurn(BaseModel):
    role: str
    content: str
    events: list[dict] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    history: list[ChatTurn] = Field(default_factory=list)


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _meaningful_tokens(text: str) -> set[str]:
    return {
        token for token in _tokenize(text) if token not in STOPWORDS and len(token) > 1
    }


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _event_point_to_datetime(
    value: Optional[str], is_end: bool = False
) -> Optional[datetime]:
    if not value:
        return None
    if "T" in value:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    parsed_date = date.fromisoformat(value)
    if is_end:
        return datetime.combine(parsed_date, datetime.max.time(), tzinfo=UTC)
    return datetime.combine(parsed_date, datetime.min.time(), tzinfo=UTC)


def _event_range(event: dict) -> tuple[Optional[datetime], Optional[datetime]]:
    start = _event_point_to_datetime(
        event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
    )
    end_datetime = event.get("end", {}).get("dateTime")
    end_date = event.get("end", {}).get("date")
    if end_datetime:
        end = _event_point_to_datetime(end_datetime, is_end=True)
    elif end_date:
        # Google Calendar all-day events use an exclusive end date.
        end = datetime.combine(
            date.fromisoformat(end_date), datetime.min.time(), tzinfo=UTC
        ) - timedelta(microseconds=1)
    else:
        end = None
    return start, end


def _overlaps_range(
    event: dict, start_iso: Optional[str], end_iso: Optional[str]
) -> bool:
    if not start_iso and not end_iso:
        return True

    event_start, event_end = _event_range(event)
    if not event_start:
        return False
    if not event_end:
        event_end = event_start

    range_start = _event_point_to_datetime(start_iso) if start_iso else None
    range_end = _event_point_to_datetime(end_iso, is_end=True) if end_iso else None

    if range_start and event_end < range_start:
        return False
    if range_end and event_start > range_end:
        return False
    return True


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
    attendee_text = ", ".join(
        attendee.get("email", "")
        for attendee in event.get("attendees", [])
        if attendee.get("email")
    )
    parts = [
        f"calendar {calendar_name}",
        f"title {event.get('title') or '(No title)'}",
    ]
    if start:
        parts.append(f"start {start}")
    if end:
        parts.append(f"end {end}")
    location = event.get("location", "")
    if location:
        parts.append(f"location {location}")
    description = (event.get("description") or "").strip()
    if description:
        # Cap description length to avoid bloating the embedding input.
        parts.append(f"description {description[:300]}")
    if attendee_text:
        parts.append(f"attendees {attendee_text}")
    return " | ".join(parts)


def _format_event_line(event: dict, calendar_lookup: dict[str, dict]) -> str:
    calendar_name = calendar_lookup.get(event.get("calendarId"), {}).get(
        "name", event.get("calendarId", "primary")
    )
    start = (
        event.get("start", {}).get("dateTime")
        or event.get("start", {}).get("date")
        or ""
    )
    end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date") or ""
    return f"[{calendar_name}] {event.get('title', '(No title)')} | {start} -> {end} | {event.get('location', '')}".strip()


def _parse_sample_questions(text: str) -> list[str]:
    questions: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        _, _, question = line.partition(". ")
        questions.append(question or line)
    return questions


def _sample_paths() -> list[Path]:
    primary_path = get_sample_questions_path()
    paths = [primary_path]

    if primary_path.resolve() == DEFAULT_SAMPLE_QUESTIONS_FILE.resolve():
        action_dir = get_action_sample_questions_dir()
        if action_dir.exists():
            paths.append(action_dir)

    return paths


def _infer_action_label_from_filename(path: Path) -> Optional[str]:
    lowered_name = path.name.lower()
    for action in ACTION_SAMPLE_GROUPS:
        prefix = action.replace("_event", "")
        if prefix in lowered_name:
            return action
    return None


def _load_sample_corpus() -> dict[str, Any]:
    all_questions: list[str] = []
    action_questions: dict[str, list[str]] = {
        action: [] for action in ACTION_SAMPLE_GROUPS
    }
    sources: list[str] = []

    for path in _sample_paths():
        if not path.exists():
            continue

        if path.is_dir():
            for sample_file in sorted(path.glob("*.txt")):
                questions = _parse_sample_questions(
                    sample_file.read_text(encoding="utf-8")
                )
                all_questions.extend(questions)
                action = _infer_action_label_from_filename(sample_file)
                if action:
                    action_questions[action].extend(questions)
                sources.append(str(sample_file))
            continue

        questions = _parse_sample_questions(path.read_text(encoding="utf-8"))
        all_questions.extend(questions)
        sources.append(str(path))

    deduped_all_questions = list(dict.fromkeys(all_questions))
    deduped_action_questions = {
        action: list(dict.fromkeys(questions))
        for action, questions in action_questions.items()
    }

    return {
        "all": deduped_all_questions,
        "by_action": deduped_action_questions,
        "sources": sources,
    }


@lru_cache(maxsize=1)
def _load_sample_questions() -> list[str]:
    return _load_sample_corpus()["all"]


@lru_cache(maxsize=1)
def _load_action_sample_questions() -> dict[str, list[str]]:
    return _load_sample_corpus()["by_action"]


def _infer_requested_action(message: str) -> str:
    lowered = message.lower()
    if any(keyword in lowered for keyword in ["create", "schedule", "book", "add"]):
        return "create_event"
    if any(
        keyword in lowered
        for keyword in ["update", "move", "reschedule", "change", "edit", "modify"]
    ):
        return "update_event"
    if any(keyword in lowered for keyword in ["delete", "remove", "cancel"]):
        return "delete_event"
    return "answer"


def _rank_texts(
    query: str, texts: list[str], client: OllamaClient, top_k: int
) -> list[tuple[int, float]]:
    if not texts:
        return []

    query_tokens = _tokenize(query)
    lexical_scores: list[tuple[int, float]] = []
    for index, text in enumerate(texts):
        text_tokens = _tokenize(text)
        overlap = len(query_tokens & text_tokens)
        lexical_scores.append(
            (index, overlap + (0.25 if query.lower() in text.lower() else 0.0))
        )

    lexical_scores.sort(key=lambda item: item[1], reverse=True)
    shortlist_size = max(top_k * 6, 12)
    has_lexical_match = any(score > 0 for _, score in lexical_scores)
    if len(texts) <= max(top_k * 20, 80) or not has_lexical_match:
        candidate_indices = list(range(len(texts)))
    else:
        candidate_indices = [index for index, _ in lexical_scores[:shortlist_size]]
    candidate_texts = [texts[index] for index in candidate_indices]
    embeddings = client.embed_texts([query, *candidate_texts])
    query_embedding = embeddings[0]
    lexical_lookup = dict(lexical_scores)
    ranked: list[tuple[int, float]] = []
    for index, embedding in zip(candidate_indices, embeddings[1:]):
        ranked.append(
            (
                index,
                _cosine_similarity(query_embedding, embedding)
                + (lexical_lookup.get(index, 0.0) * 0.05),
            )
        )
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked[:top_k]


def _primary_calendar_id(calendars: list[dict]) -> str:
    return next(
        (calendar["id"] for calendar in calendars if calendar.get("primary")),
        "primary",
    )


def _default_calendar_id(action: str, calendars: list[dict]) -> str:
    if action == "create_event":
        return _primary_calendar_id(calendars)
    return "all"


def _resolve_calendar_id(
    requested_value: Optional[str], calendars: list[dict], default_value: str
) -> str:
    if not requested_value:
        return default_value

    normalized = requested_value.strip().lower()
    for calendar in calendars:
        if (
            calendar["id"].lower() == normalized
            or calendar["name"].lower() == normalized
        ):
            return calendar["id"]
    for calendar in calendars:
        if normalized in calendar["name"].lower():
            return calendar["id"]
    return requested_value


def _fallback_plan(message: str, calendars: list[dict]) -> dict[str, Any]:
    action = _infer_requested_action(message)
    return {
        "action": action,
        "needs_clarification": action != "answer",
        "clarification_question": "Please tell me the exact event title and date/time you want me to change."
        if action != "answer"
        else "",
        "calendar_id": _default_calendar_id(action, calendars),
        "search_query": message,
        "target_hint": "",
        "time_min": "",
        "time_max": "",
        "event": {},
        "updates": {},
    }


def _parse_history(history: list[ChatTurn]) -> str:
    if not history:
        return ""
    trimmed = history[-6:]
    return "\n".join(f"{turn.role}: {turn.content}" for turn in trimmed)


def _dedupe_events(events: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    unique_events: list[dict] = []
    for event in events:
        key = (event.get("calendarId", "primary"), event.get("id", ""))
        if key in seen:
            continue
        seen.add(key)
        unique_events.append(event)
    return unique_events


def _history_events(history: list[ChatTurn]) -> list[dict]:
    events: list[dict] = []
    for turn in history:
        if turn.role != "assistant":
            continue
        events.extend(turn.events or [])
    return _dedupe_events(events)


def _plan_chat_action(
    request_message: str,
    history: list[ChatTurn],
    history_events: list[dict],
    calendars: list[dict],
    sample_questions: list[str],
    client: OllamaClient,
) -> dict[str, Any]:
    requested_action = _infer_requested_action(request_message)
    action_samples = _load_action_sample_questions().get(requested_action, [])
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
    now = datetime.now().astimezone().isoformat()
    calendar_lines = "\n".join(
        f"- {calendar['name']} ({calendar['id']})" for calendar in calendars
    )
    calendar_lookup = {calendar["id"]: calendar for calendar in calendars}
    # Include events from previous turns so the LLM can reference their times
    # (e.g. "keep it the same time" after a reschedule clarification).
    history_event_lines = (
        "\n".join(
            f"- {_format_event_line(event, calendar_lookup)}"
            for event in history_events[:5]
        )
        or "none"
    )

    system_prompt = (
        "You are a planner for a Google Calendar assistant. "
        "Return strict JSON only. Convert relative dates using the supplied current datetime. "
        "Use these actions only: answer, create_event, update_event, delete_event. "
        "If the user wants information, use action answer. "
        "Set all_time to true ONLY when the user explicitly asks for data across all time "
        "(e.g. 'all time', 'ever', 'all events ever'). "
        "Set list_all to true when the user asks to list, show, or count ALL of their events "
        "(e.g. 'list all my events', 'show everything', 'count all events', 'list every event'). "
        "Set exclude_holiday_calendars to true when the user asks to exclude holidays, festivals, "
        "or birthday calendars. "
        "If key details are missing, set needs_clarification true and ask a short question. "
        "For update/delete where the user says 'keep it the same' or 'same time', use the "
        "HISTORY_EVENTS times to fill in the start/end values — do NOT ask again. "
        "Use ISO 8601 datetime strings with timezone offsets for timed events. "
        "Use YYYY-MM-DD for all-day events. "
        "For recurring events, return Google Calendar recurrence rules like RRULE:FREQ=WEEKLY;BYDAY=MO."
    )
    user_prompt = (
        f"CURRENT_DATETIME: {now}\n"
        f"AVAILABLE_CALENDARS:\n{calendar_lines}\n\n"
        f"RECENT_HISTORY:\n{_parse_history(history) or 'none'}\n\n"
        f"HISTORY_EVENTS (events shown in recent assistant responses — use their times when user says 'keep the same'):\n{history_event_lines}\n\n"
        f"INFERRED_REQUESTED_ACTION: {requested_action}\n\n"
        f"SIMILAR_SAMPLE_QUESTIONS:\n"
        + ("\n".join(f"- {question}" for question in similar_questions) or "none")
        + "\n\n"
        f"ACTION_SPECIFIC_EXAMPLES:\n"
        + ("\n".join(f"- {question}" for question in similar_action_samples) or "none")
        + "\n\n"
        "Return JSON with this shape:\n"
        "{\n"
        '  "action": "answer|create_event|update_event|delete_event",\n'
        '  "all_time": false,\n'
        '  "list_all": false,\n'
        '  "exclude_holiday_calendars": false,\n'
        '  "needs_clarification": false,\n'
        '  "clarification_question": "",\n'
        '  "calendar_id": "",\n'
        '  "search_query": "",\n'
        '  "target_hint": "",\n'
        '  "time_min": "",\n'
        '  "time_max": "",\n'
        '  "event": {"title": "", "start": "", "end": "", "all_day": false, "description": "", "location": "", "visibility": "", "recurrence": [], "attendee_emails": [], "reminder_minutes": []},\n'
        '  "updates": {"title": "", "start": "", "end": "", "all_day": false, "description": "", "location": "", "visibility": "", "recurrence": [], "attendee_emails": [], "reminder_minutes": []}\n'
        "}\n\n"
        f"USER_MESSAGE: {request_message}"
    )
    try:
        plan = client.chat_json(system_prompt, user_prompt)
    except OllamaClientError:
        return _fallback_plan(request_message, calendars)

    if not isinstance(plan, dict) or not plan.get("action"):
        return _fallback_plan(request_message, calendars)
    return plan


def _filter_events(events: list[dict], plan: dict[str, Any]) -> list[dict]:
    return [
        event
        for event in events
        if _overlaps_range(
            event, plan.get("time_min") or None, plan.get("time_max") or None
        )
    ]


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
    # Require a minimum semantic similarity; below this the match is too weak.
    if top_score < 0.15:
        return None, options
    return top_event, options


def _normalize_reminders(reminder_minutes: list[Any]) -> Optional[dict]:
    cleaned_minutes = []
    for value in reminder_minutes:
        try:
            cleaned_minutes.append(int(value))
        except (TypeError, ValueError):
            continue
    if not cleaned_minutes:
        return None
    return {
        "useDefault": False,
        "overrides": [
            {"method": "popup", "minutes": minutes} for minutes in cleaned_minutes
        ],
    }


def _build_event_body(
    payload: dict[str, Any], existing_event: Optional[dict] = None
) -> dict[str, Any]:
    body: dict[str, Any] = {}

    for source_key, target_key in [
        ("title", "summary"),
        ("description", "description"),
        ("location", "location"),
        ("visibility", "visibility"),
    ]:
        value = payload.get(source_key)
        if value:
            body[target_key] = value

    recurrence = payload.get("recurrence") or []
    if isinstance(recurrence, str):
        recurrence = [recurrence]
    if recurrence:
        body["recurrence"] = recurrence

    attendee_emails = [
        email
        for email in payload.get("attendee_emails", [])
        if isinstance(email, str) and "@" in email
    ]
    if attendee_emails:
        body["attendees"] = [{"email": email} for email in attendee_emails]

    reminders = _normalize_reminders(payload.get("reminder_minutes", []))
    if reminders:
        body["reminders"] = reminders

    all_day = bool(payload.get("all_day"))
    start_value = payload.get("start")
    end_value = payload.get("end")

    if start_value:
        if all_day:
            start_date = date.fromisoformat(start_value[:10])
            if end_value:
                end_date = date.fromisoformat(end_value[:10])
            elif existing_event and existing_event.get("end", {}).get("date"):
                existing_end = date.fromisoformat(existing_event["end"]["date"])
                existing_start = date.fromisoformat(existing_event["start"]["date"])
                end_date = start_date + (existing_end - existing_start)
            else:
                end_date = start_date + timedelta(days=1)
            body["start"] = {"date": start_date.isoformat()}
            body["end"] = {"date": end_date.isoformat()}
        else:
            start_dt = datetime.fromisoformat(start_value.replace("Z", "+00:00"))
            if end_value:
                end_dt = datetime.fromisoformat(end_value.replace("Z", "+00:00"))
            elif (
                existing_event
                and existing_event.get("start", {}).get("dateTime")
                and existing_event.get("end", {}).get("dateTime")
            ):
                old_start = datetime.fromisoformat(
                    existing_event["start"]["dateTime"].replace("Z", "+00:00")
                )
                old_end = datetime.fromisoformat(
                    existing_event["end"]["dateTime"].replace("Z", "+00:00")
                )
                end_dt = start_dt + (old_end - old_start)
            else:
                end_dt = start_dt + timedelta(hours=1)
            body["start"] = {"dateTime": start_dt.isoformat()}
            body["end"] = {"dateTime": end_dt.isoformat()}

    return body


def _answer_from_context(
    request_message: str,
    history: list[ChatTurn],
    plan: dict[str, Any],
    relevant_events: list[dict],
    sample_questions: list[str],
    calendars: list[dict],
    client: OllamaClient,
) -> str:
    calendar_lookup = {calendar["id"]: calendar for calendar in calendars}
    question_lines = (
        "\n".join(f"- {question}" for question in sample_questions[:6]) or "none"
    )
    event_lines = (
        "\n".join(
            f"- {_format_event_line(event, calendar_lookup)}"
            for event in relevant_events
        )
        or "none"
    )
    system_prompt = (
        "You are a helpful Google Calendar assistant. "
        "Answer the user's question using the RELEVANT_EVENTS list and CURRENT_DATETIME supplied below. "
        "You may use general knowledge about dates, times, and days of the week. "
        "If the event list is empty or does not contain enough information to fully answer, say so honestly. "
        "Never fabricate or guess calendar events that are not in the list. "
        "Be concise and direct. Format event times in a human-readable way (e.g. 'Monday 14 April at 3 PM')."
    )
    user_prompt = (
        f"CURRENT_DATETIME: {datetime.now().astimezone().isoformat()}\n"
        f"RECENT_HISTORY:\n{_parse_history(history) or 'none'}\n\n"
        f"PLANNER_OUTPUT:\n{plan}\n\n"
        f"SIMILAR_SAMPLE_QUESTIONS (for context only):\n{question_lines}\n\n"
        f"RELEVANT_EVENTS:\n{event_lines}\n\n"
        f"USER_MESSAGE: {request_message}"
    )
    return client.chat_text(system_prompt, user_prompt)


def _resolve_target_event(
    request_message: str,
    plan: dict[str, Any],
    events: list[dict],
    calendars: list[dict],
    client: OllamaClient,
) -> tuple[Optional[dict], list[dict]]:
    if not events:
        return None, []

    calendar_lookup = {calendar["id"]: calendar for calendar in calendars}
    query = plan.get("target_hint") or plan.get("search_query") or request_message
    normalized_query = query.strip().lower()
    query_tokens = _meaningful_tokens(query)
    if normalized_query:
        exact_title_matches = [
            event
            for event in events
            if event.get("title", "").strip().lower() == normalized_query
        ]
        if len(exact_title_matches) == 1:
            return exact_title_matches[0], exact_title_matches

        contains_title_matches = [
            event
            for event in events
            if normalized_query in event.get("title", "").strip().lower()
        ]
        if len(contains_title_matches) == 1:
            return contains_title_matches[0], contains_title_matches

    if query_tokens:
        lexical_matches = []
        for event in events:
            title_tokens = _meaningful_tokens(event.get("title", ""))
            overlap = len(query_tokens & title_tokens)
            if overlap:
                lexical_matches.append((event, overlap))

        lexical_matches.sort(key=lambda item: item[1], reverse=True)
        if lexical_matches:
            top_overlap = lexical_matches[0][1]
            strongest_matches = [
                event for event, overlap in lexical_matches if overlap == top_overlap
            ]
            if top_overlap >= 1 and len(strongest_matches) == 1:
                return strongest_matches[0], strongest_matches
            if strongest_matches:
                matched_event, ranked_options = _select_ranked_event(
                    query, strongest_matches, calendar_lookup, client
                )
                if matched_event:
                    return matched_event, strongest_matches
                if ranked_options:
                    return None, ranked_options

    if len(events) == 1 and query_tokens:
        return None, events[:1]

    return _select_ranked_event(query, events, calendar_lookup, client)


def _build_action_summary(action: str, event: dict, calendars: list[dict]) -> str:
    calendar_lookup = {calendar["id"]: calendar for calendar in calendars}
    return {
        "create_event": f"Created '{event.get('title')}' on {calendar_lookup.get(event.get('calendarId'), {}).get('name', event.get('calendarId', 'primary'))}.",
        "update_event": f"Updated '{event.get('title')}'.",
        "delete_event": f"Deleted '{event.get('title')}'.",
    }.get(action, "Completed calendar action.")


@router.get("/health")
def health():
    config = get_ollama_config()
    client = OllamaClient(
        base_url=config["base_url"],
        chat_model=config["chat_model"],
        embed_model=config["embed_model"],
    )
    try:
        tags = client.ensure_ready()
    except OllamaClientError as exc:
        raise HTTPException(status_code=503, detail={"message": str(exc)}) from exc

    return {
        "status": "ok",
        "ollama": config,
        "models": [model.get("name") for model in tags.get("models", [])],
        "sample_questions_loaded": len(_load_sample_questions()),
        "sample_questions_path": str(get_sample_questions_path()),
        "sample_sources": _load_sample_corpus()["sources"],
        "action_sample_counts": {
            action: len(questions)
            for action, questions in _load_action_sample_questions().items()
        },
    }


@router.post("")
def chat(request: Request, payload: ChatRequest):
    tokens = get_tokens(request)
    if not tokens:
        raise HTTPException(status_code=401, detail="Not authenticated")

    creds = build_credentials(tokens)
    try:
        calendars = list_calendars(creds)
    except HttpError as exc:
        translate_google_api_error(exc)

    ollama_config = get_ollama_config()
    client = OllamaClient(
        base_url=ollama_config["base_url"],
        chat_model=ollama_config["chat_model"],
        embed_model=ollama_config["embed_model"],
    )
    sample_questions = _load_sample_questions()

    # Extract history events BEFORE planning so the planner can see referenced
    # event details (e.g. start/end times when user says "keep it the same").
    history_events = _history_events(payload.history)

    try:
        plan = _plan_chat_action(
            payload.message, payload.history, history_events, calendars, sample_questions, client
        )
    except OllamaClientError as exc:
        raise HTTPException(status_code=503, detail={"message": str(exc)}) from exc

    action = plan.get("action", "answer")
    resolved_calendar_id = _resolve_calendar_id(
        plan.get("calendar_id"), calendars, _default_calendar_id(action, calendars)
    )

    if plan.get("needs_clarification"):
        # For update/delete: eagerly fetch the target event so it appears in
        # history.events on the follow-up turn. This lets the LLM resolve
        # "keep it the same" type replies against the event's actual times.
        clarification_events: list[dict] = []
        if action in {"update_event", "delete_event"}:
            try:
                prefetch_candidates, _ = fetch_all_events(
                    creds,
                    calendar_ids=[resolved_calendar_id]
                    if resolved_calendar_id and resolved_calendar_id != "all"
                    else None,
                    time_min=plan.get("time_min") or None,
                    time_max=plan.get("time_max") or None,
                )
                target_prefetch, _ = _resolve_target_event(
                    payload.message,
                    plan,
                    _dedupe_events([*history_events, *prefetch_candidates]),
                    calendars,
                    client,
                )
                if target_prefetch:
                    clarification_events = [target_prefetch]
            except (HttpError, OllamaClientError):
                pass  # Best-effort — don't fail the clarification response.
        return {
            "answer": plan.get("clarification_question")
            or "I need one more detail before I can help with that.",
            "mode": "clarification",
            "actions": [],
            "events": clarification_events,
            "plan": plan,
        }

    # Apply a sensible default time window for answer queries when the LLM did
    # not set explicit bounds AND the user did not ask for all-time / list-all data.
    # Use -30 / +90 days so events a month in the past are not silently excluded.
    if (
        action == "answer"
        and not plan.get("time_min")
        and not plan.get("time_max")
        and not plan.get("all_time")
        and not plan.get("list_all")
    ):
        _now = datetime.now(UTC)
        plan["time_min"] = (_now - timedelta(days=30)).isoformat()
        plan["time_max"] = (_now + timedelta(days=90)).isoformat()

    try:
        candidate_events, scanned_calendar_ids = fetch_all_events(
            creds,
            calendar_ids=[resolved_calendar_id]
            if resolved_calendar_id and resolved_calendar_id != "all"
            else None,
            q=(plan.get("search_query") or None) if action == "answer" else None,
            time_min=plan.get("time_min") or None,
            time_max=plan.get("time_max") or None,
        )
    except HttpError as exc:
        translate_google_api_error(exc)

    filtered_events = _filter_events(
        _dedupe_events([*history_events, *candidate_events]), plan
    )

    # Remove holiday/birthday calendar events when the user explicitly asked to.
    if plan.get("exclude_holiday_calendars"):
        holiday_calendar_ids = {
            cal["id"]
            for cal in calendars
            if cal.get("isHoliday") or cal.get("isBirthday")
        }
        filtered_events = [
            event
            for event in filtered_events
            if event.get("calendarId") not in holiday_calendar_ids
        ]

    if action == "answer":
        try:
            ranked_questions = (
                _rank_texts(payload.message, sample_questions, client, top_k=6)
                if sample_questions
                else []
            )
            relevant_questions = [
                sample_questions[index] for index, _ in ranked_questions
            ]
            calendar_lookup = {calendar["id"]: calendar for calendar in calendars}
            if plan.get("list_all") or plan.get("all_time"):
                # User wants every event — skip relevance ranking, return all.
                relevant_events = filtered_events
            elif filtered_events:
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
            else:
                relevant_events = []
            answer = _answer_from_context(
                payload.message,
                payload.history,
                plan,
                relevant_events,
                relevant_questions,
                calendars,
                client,
            )
        except OllamaClientError as exc:
            raise HTTPException(status_code=503, detail={"message": str(exc)}) from exc

        return {
            "answer": answer,
            "mode": "answer",
            "actions": [],
            "events": relevant_events[:50],
            "plan": plan,
            "calendarsScanned": scanned_calendar_ids,
        }

    if action == "create_event":
        event_payload = plan.get("event") or {}
        if not event_payload.get("title") or not event_payload.get("start"):
            return {
                "answer": "I need at least an event title and start time to create that calendar event.",
                "mode": "clarification",
                "actions": [],
                "events": [],
                "plan": plan,
            }

        body = _build_event_body(event_payload)
        try:
            created = create_event(creds, resolved_calendar_id or "primary", body)
        except HttpError as exc:
            translate_google_api_error(exc)
        return {
            "answer": _build_action_summary(action, created, calendars),
            "mode": "action",
            "actions": [
                {
                    "type": action,
                    "calendarId": created.get("calendarId"),
                    "eventId": created.get("id"),
                }
            ],
            "events": [created],
            "plan": plan,
        }

    if action in {"update_event", "delete_event"}:
        try:
            target_event, options = _resolve_target_event(
                payload.message, plan, filtered_events, calendars, client
            )
        except OllamaClientError as exc:
            raise HTTPException(status_code=503, detail={"message": str(exc)}) from exc
        if not target_event:
            option_lines = "\n".join(
                f"- {_format_event_line(event, {calendar['id']: calendar for calendar in calendars})}"
                for event in options[:3]
            )
            message = "I could not identify a single matching event."
            if option_lines:
                message += f" Please clarify which one you mean:\n{option_lines}"
            return {
                "answer": message,
                "mode": "clarification",
                "actions": [],
                "events": options[:3],
                "plan": plan,
            }

        if action == "delete_event":
            try:
                delete_event(creds, target_event["calendarId"], target_event["id"])
            except HttpError as exc:
                translate_google_api_error(exc)
            return {
                "answer": _build_action_summary(action, target_event, calendars),
                "mode": "action",
                "actions": [
                    {
                        "type": action,
                        "calendarId": target_event.get("calendarId"),
                        "eventId": target_event.get("id"),
                    }
                ],
                "events": [target_event],
                "plan": plan,
            }

        update_payload = plan.get("updates") or {}
        if not update_payload:
            return {
                "answer": "I found the event, but I still need to know what should change.",
                "mode": "clarification",
                "actions": [],
                "events": [target_event],
                "plan": plan,
            }

        body = _build_event_body(update_payload, existing_event=target_event)
        if not body:
            return {
                "answer": "I found the event, but I could not extract any specific updates to apply.",
                "mode": "clarification",
                "actions": [],
                "events": [target_event],
                "plan": plan,
            }

        try:
            updated = update_event(
                creds, target_event["calendarId"], target_event["id"], body
            )
        except HttpError as exc:
            translate_google_api_error(exc)
        return {
            "answer": _build_action_summary(action, updated, calendars),
            "mode": "action",
            "actions": [
                {
                    "type": action,
                    "calendarId": updated.get("calendarId"),
                    "eventId": updated.get("id"),
                }
            ],
            "events": [updated],
            "plan": plan,
        }

    return {
        "answer": "I could not determine how to handle that request yet.",
        "mode": "clarification",
        "actions": [],
        "events": [],
        "plan": plan,
    }
