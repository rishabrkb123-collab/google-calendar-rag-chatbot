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
    get_groq_config,
    get_ollama_config,
    get_sample_questions_path,
)
from backend.ollama_client import OllamaClient, OllamaClientError
from backend.session import get_tokens
from backend.vector_store import get_vector_store
from googleapiclient.errors import HttpError


router = APIRouter(prefix="/chat")


def _build_llm_client():
    """Return a GroqClient when GROQ_API_KEY is set, otherwise OllamaClient."""
    groq_cfg = get_groq_config()
    if groq_cfg["api_key"]:
        from backend.groq_client import GroqClient
        return GroqClient(api_key=groq_cfg["api_key"], chat_model=groq_cfg["chat_model"])
    cfg = get_ollama_config()
    return OllamaClient(
        base_url=cfg["base_url"],
        chat_model=cfg["chat_model"],
        api_key=cfg.get("api_key", ""),
    )

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

_PRONOUN_RE = re.compile(
    r"\b(it|this|that|the same one?|that one|the event|that event|this event)\b",
    re.IGNORECASE,
)
_DELETE_ACTION_RE = re.compile(r"\b(cancel|delete|remove|drop)\b", re.IGNORECASE)
_UPDATE_ACTION_RE = re.compile(
    r"\b(update|move|reschedule|change|edit|modify|shift|rename|postpone|delay)\b",
    re.IGNORECASE,
)
_CREATE_ACTION_RE = re.compile(
    r"\b(create|schedule|book|add|set up|make)\b", re.IGNORECASE
)
_ANSWER_ACTION_RE = re.compile(
    r"\b(what|when|which|who|list|show|find|search|count|availability|available|am i free|do i have|free slot|free time)\b",
    re.IGNORECASE,
)

ACTION_SAMPLE_GROUPS = ("create_event", "update_event", "delete_event")


class ChatTurn(BaseModel):
    role: str
    content: str
    events: list[dict] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    history: list[ChatTurn] = Field(default_factory=list)
    # When the user taps a suggested event card in the UI, the frontend passes
    # the event's ID here so the backend can skip fuzzy matching entirely.
    selected_event_id: Optional[str] = None
    # The frontend echoes the pending_plan from the last clarification response
    # so the original action + updates survive across clarification turns.
    pending_plan: Optional[dict] = None


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _meaningful_tokens(text: str) -> set[str]:
    return {
        token for token in _tokenize(text) if token not in STOPWORDS and len(token) > 1
    }


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
    attendee_parts = []
    for attendee in event.get("attendees", []):
        name = attendee.get("displayName") or attendee.get("email", "").split("@")[0]
        if name:
            attendee_parts.append(name)
    attendee_text = ", ".join(attendee_parts)
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


def _event_match_text(event: dict) -> str:
    attendee_parts = []
    for attendee in event.get("attendees", []):
        display_name = attendee.get("displayName") or attendee.get("email", "").split("@")[0]
        if display_name:
            attendee_parts.append(display_name)
    parts = [
        event.get("title", ""),
        event.get("location", ""),
        (event.get("description") or "")[:300],
        event.get("organizer", ""),
        " ".join(attendee_parts),
    ]
    return " | ".join(part for part in parts if part)


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
    if _DELETE_ACTION_RE.search(message):
        return "delete_event"
    if _UPDATE_ACTION_RE.search(message):
        return "update_event"
    if _CREATE_ACTION_RE.search(message):
        return "create_event"
    if message.strip().endswith("?") or _ANSWER_ACTION_RE.search(message):
        return "answer"
    return "answer"



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
    return default_value


def _extract_target_hint_from_message(message: str) -> str:
    """Best-effort extraction of event name from 'delete/change [NAME] appointment' patterns."""
    pattern = re.compile(
        r"(?:delete|remove|cancel|update|change|move|reschedule|edit|shift)\s+"
        r"(?:my\s+|the\s+|an?\s+)?(['\"]?)(.+?)\1"
        r"\s*(?:appointment|event|meeting|schedule|reminder)?(?:\s+(?:from|to|on|at|by)\b.*)?$",
        re.IGNORECASE,
    )
    m = pattern.search(message.strip())
    if m:
        name = m.group(2).strip()
        # Filter out noise phrases
        noise = {"appointment", "event", "meeting", "schedule", "reminder", "the", "my", "an", "a"}
        if name.lower() not in noise and len(name) > 1:
            return name
    return ""


def _fallback_plan(message: str, calendars: list[dict]) -> dict[str, Any]:
    action = _infer_requested_action(message)
    target = _extract_target_hint_from_message(message) if action != "answer" else ""
    return {
        "action": action,
        "needs_clarification": action != "answer" and not target,
        "clarification_question": (
            "I couldn't find that event. Please check the event name and try again."
            if action != "answer" and not target
            else ""
        ),
        "calendar_id": _default_calendar_id(action, calendars),
        "search_query": target or message,
        "target_hint": target,
        "time_min": "",
        "time_max": "",
        "event": {},
        "updates": {},
    }


def _parse_history(history: list[ChatTurn]) -> str:
    if not history:
        return ""
    trimmed = history[-10:]
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


def _pending_plan_context(pending_plan: Optional[dict]) -> str:
    """Format a pending_plan as an explicit context block for the planner prompt."""
    if not pending_plan:
        return ""
    pp_action = pending_plan.get("action", "")
    if pp_action not in {"update_event", "delete_event"}:
        return ""
    lines = [
        "ACTIVE_OPERATION (already established — do NOT change the action or ask again):",
        f"  action      : {pp_action}",
    ]
    if pending_plan.get("target_hint"):
        lines.append(f"  target event: {pending_plan['target_hint']}")
    updates = {k: v for k, v in (pending_plan.get("updates") or {}).items() if v}
    if updates:
        lines.append(f"  pending updates: {updates}")
    lines.append(
        "The user's current message is COMPLETING this operation (selecting the event, "
        "confirming, or providing a missing detail). Keep action = "
        f'"{pp_action}" and needs_clarification = false. '
        "Only update the fields the user just provided; preserve everything else."
    )
    return "\n".join(lines)


def _plan_chat_action(
    request_message: str,
    history: list[ChatTurn],
    history_events: list[dict],
    calendars: list[dict],
    sample_questions: list[str],
    client: OllamaClient,
    pending_plan: Optional[dict] = None,
) -> dict[str, Any]:
    requested_action = _infer_requested_action(request_message)
    # When a pending_plan exists, trust it over the raw keyword inference so
    # that follow-up messages like "I mean the X event" don't override the action.
    if pending_plan and pending_plan.get("action") in {"update_event", "delete_event"}:
        requested_action = pending_plan["action"]

    action_samples = _load_action_sample_questions().get(requested_action, [])
    vs = get_vector_store()
    vs.seed_sample_questions(sample_questions)
    similar_questions = vs.query_sample_questions(request_message, top_k=6) if sample_questions else []
    similar_action_samples = (
        [action_samples[i] for i, _ in vs.rank_texts(request_message, action_samples, top_k=6)]
        if action_samples
        else []
    )
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
    pending_context = _pending_plan_context(pending_plan)

    system_prompt = (
        "You are the planning layer of a Google Calendar assistant. "
        "Your only job is to parse the user's intent and return a strict JSON plan — no prose, no explanation. "
        "Available actions: answer, create_event, update_event, delete_event. "
        "Use 'answer' for any information request (listing, searching, counting, asking about events). "
        "Use 'create_event' only when the user explicitly wants to add a new event. "
        "Use 'update_event' / 'delete_event' only when the user wants to modify or remove a specific existing event. "
        "Flags:\n"
        "  all_time  — set true ONLY when the user says 'all time', 'ever', 'all events ever'.\n"
        "  list_all  — set true when the user says 'list all', 'show everything', 'count all events'.\n"
        "  exclude_holiday_calendars — set true when the user explicitly says to exclude holidays/birthdays.\n"
        "  needs_clarification — set true ONLY when a truly required field is COMPLETELY absent and cannot "
        "be inferred from any context. Do NOT set needs_clarification=true in these common cases:\n"
        "    - User gives event name + new date (even without exact time) → needs_clarification=false.\n"
        "    - User says 'same time/timing/timings' → needs_clarification=false; set updates.start to "
        "date-only (YYYY-MM-DD); backend preserves existing time automatically.\n"
        "    - User confirms, says 'yes', 'ok', 'correct', or selects a shown event → needs_clarification=false.\n"
        "    - The target event can be inferred from RECENT_HISTORY or HISTORY_EVENTS → needs_clarification=false.\n"
        "  When needs_clarification IS required: ask exactly ONE short, specific question. Never ask for "
        "information that was already provided earlier in the conversation.\n"
        "Date-only update rule: when the user says 'same time/timing/timings' alongside a new date, set "
        "updates.start = 'YYYY-MM-DD' (date only, no time component). The backend handles time preservation.\n"
        "Datetime rules:\n"
        "  - Convert all relative dates ('tomorrow', 'next Monday') using CURRENT_DATETIME.\n"
        "  - Use ISO 8601 with timezone offset for timed events (e.g. 2026-04-21T14:00:00+05:30).\n"
        "  - Use YYYY-MM-DD for all-day events and for date-only updates.\n"
        "  - For recurring events use RRULE strings (e.g. RRULE:FREQ=WEEKLY;BYDAY=MO).\n"
        "Target event name extraction rules (CRITICAL — follow exactly):\n"
        "  Pattern: '[action] [NAME] appointment/event/meeting/schedule' → target_hint = NAME, needs_clarification = false.\n"
        "  Examples:\n"
        "    'delete Sample title appointment' → target_hint='Sample title', action='delete_event'\n"
        "    'remove hello appi event' → target_hint='Hello Appi', action='delete_event'\n"
        "    'change dentist appointment to friday' → target_hint='Dentist', action='update_event'\n"
        "  Rule: extract the NAME between the action verb and the word 'appointment/event/meeting' (or end of phrase).\n"
        "  NEVER set needs_clarification=true when the user has already stated an event name.\n"
        "  Always set search_query = target_hint for update/delete.\n"
        "Correction rule: when the user starts their message with 'no', 'not', 'I mean', 'actually', or 'wait' "
        "after the assistant showed a wrong event, treat it as a NEW target identification for the same action. "
        "Extract the corrected event name or date from what follows. Do NOT repeat the previous event.\n"
        "  Example: 'no the one which is on april 1' → keep action='delete_event', set time_min/time_max around April 1, "
        "set target_hint to whatever event the user described, needs_clarification=false.\n"
        "Clarification follow-up rule: if RECENT_HISTORY shows the assistant asked about an event, "
        "the user's reply IS the answer — keep the original action, copy the event title from "
        "RECENT_HISTORY into both target_hint and search_query. Do NOT ask again. "
        "Pronoun rule: if the user says 'this', 'it', 'that event', or 'the same one', resolve the "
        "reference using the most recent event in HISTORY_EVENTS and set target_hint to its title. "
        "Same-time rule: if the user says 'keep it the same' or 'same time/timing/timings', and "
        "HISTORY_EVENTS has the event, fill start/end from it. If HISTORY_EVENTS is empty, set "
        "updates.start to the new date only (YYYY-MM-DD) — do NOT ask for the time."
    )
    user_prompt = (
        f"CURRENT_DATETIME: {now}\n"
        f"AVAILABLE_CALENDARS:\n{calendar_lines}\n\n"
        + (f"{pending_context}\n\n" if pending_context else "")
        + f"RECENT_HISTORY:\n{_parse_history(history) or 'none'}\n\n"
        f"HISTORY_EVENTS (events referenced in recent responses — use their times when user says 'keep the same' or resolving pronouns like 'this'/'it'):\n{history_event_lines}\n\n"
        f"INFERRED_REQUESTED_ACTION: {requested_action}\n\n"
        "SEMANTICALLY_SIMILAR_QUESTIONS (retrieved by vector search — use these to understand the "
        "user's intent and choose the correct action and fields):\n"
        + ("\n".join(f"- {question}" for question in similar_questions) or "none")
        + "\n\n"
        "ACTION_EXAMPLES (example phrasings for the inferred action — use these to calibrate "
        "field extraction such as title, time range, and target event):\n"
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
    top_k: int,
) -> list[tuple[dict, float]]:
    if not events:
        return []
    documents = [_event_to_document(event, calendar_lookup) for event in events]
    ranked_indices = get_vector_store().rank_texts(query, documents, top_k)
    return [(events[index], score) for index, score in ranked_indices]


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
    if len(events) == 1 and top_score < 0.45:
        return None, []
    if top_score < 0.25:
        return None, options
    if len(ranked) > 1 and (top_score - ranked[1][1]) < 0.10:
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
            # Date-only value (no "T"): preserve existing event's time component
            if "T" not in start_value and existing_event and existing_event.get("start", {}).get("dateTime"):
                existing_dt = datetime.fromisoformat(
                    existing_event["start"]["dateTime"].replace("Z", "+00:00")
                )
                new_date = date.fromisoformat(start_value[:10])
                start_dt = existing_dt.replace(year=new_date.year, month=new_date.month, day=new_date.day)
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
    event_lines = (
        "\n".join(
            f"- {_format_event_line(event, calendar_lookup)}"
            for event in relevant_events
        )
        or "none"
    )
    # Pass only the planner fields relevant to answering — omit internal flags.
    query_context = {
        k: plan.get(k)
        for k in ("action", "search_query", "target_hint", "time_min", "time_max")
        if plan.get(k)
    }
    system_prompt = (
        "You are the answer layer of a Google Calendar assistant. "
        "The planning layer has already determined the user's intent and fetched the relevant calendar events. "
        "Your job: answer the user's question using ONLY the RELEVANT_EVENTS list provided. "
        "Rules:\n"
        "  - Never fabricate, guess, or invent events that are not in RELEVANT_EVENTS.\n"
        "  - If RELEVANT_EVENTS is empty or does not contain enough information, say so honestly.\n"
        "  - You may use general knowledge about dates, times, and days of the week to format your answer.\n"
        "  - Format event times in a natural, human-readable way (e.g. 'Monday 14 April at 3:00 PM').\n"
        "  - Be concise and direct. Do not re-list every field of an event unless the user asked for detail.\n"
        "  - If the user asked to count events, count from RELEVANT_EVENTS only.\n"
        "  - Use CURRENT_DATETIME to describe how far away events are (e.g. 'tomorrow', 'in 3 days')."
    )
    user_prompt = (
        f"CURRENT_DATETIME: {datetime.now().astimezone().isoformat()}\n"
        f"RECENT_HISTORY:\n{_parse_history(history) or 'none'}\n\n"
        f"QUERY_CONTEXT (what the planner resolved — use this to understand what the user is looking for):\n"
        f"{query_context}\n\n"
        f"RELEVANT_EVENTS:\n{event_lines}\n\n"
        f"USER_MESSAGE: {request_message}"
    )
    return client.chat_text(system_prompt, user_prompt)


def _resolve_target_event(
    request_message: str,
    plan: dict[str, Any],
    events: list[dict],
    calendars: list[dict],
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

        contains_context_matches = [
            event
            for event in events
            if normalized_query in _event_match_text(event).strip().lower()
        ]
        if len(contains_context_matches) == 1:
            return contains_context_matches[0], contains_context_matches

    if query_tokens:
        lexical_matches = []
        for event in events:
            match_tokens = _meaningful_tokens(_event_match_text(event))
            overlap = len(query_tokens & match_tokens)
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
                    query, strongest_matches, calendar_lookup
                )
                if matched_event:
                    return matched_event, strongest_matches
                if ranked_options:
                    return None, ranked_options

    return _select_ranked_event(query, events, calendar_lookup)


def _build_action_summary(action: str, event: dict, calendars: list[dict]) -> str:
    calendar_lookup = {calendar["id"]: calendar for calendar in calendars}
    return {
        "create_event": f"Created '{event.get('title')}' on {calendar_lookup.get(event.get('calendarId'), {}).get('name', event.get('calendarId', 'primary'))}.",
        "update_event": f"Updated '{event.get('title')}'.",
        "delete_event": f"Deleted '{event.get('title')}'.",
    }.get(action, "Completed calendar action.")


def _build_confirmation_message(action: str, event: dict, body: dict) -> str:
    title = event.get("title", "this event")
    if action == "delete_event":
        start_raw = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date", "")
        date_str = ""
        if start_raw:
            try:
                dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                date_str = f" on {dt.strftime('%a, %d %b at %I:%M %p').lstrip('0')}"
            except ValueError:
                pass
        return f"Delete '{title}'{date_str}? This cannot be undone."

    new_start = body.get("start", {}).get("dateTime") or body.get("start", {}).get("date", "")
    if new_start:
        try:
            dt = datetime.fromisoformat(new_start.replace("Z", "+00:00"))
            new_start_str = dt.strftime("%a, %d %b at %I:%M %p").lstrip("0")
        except ValueError:
            new_start_str = new_start
        return f"Move '{title}' to {new_start_str}?"
    return f"Apply these changes to '{title}'?"


@router.get("/health")
def health():
    client = _build_llm_client()
    try:
        tags = client.ensure_ready()
    except OllamaClientError as exc:
        raise HTTPException(status_code=503, detail={"message": str(exc)}) from exc

    groq_cfg = get_groq_config()
    config = {"provider": "groq", "model": groq_cfg["chat_model"]} if groq_cfg["api_key"] else get_ollama_config()
    return {
        "status": "ok",
        "llm": config,
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

    client = _build_llm_client()
    sample_questions = _load_sample_questions()

    # Extract history events BEFORE planning so the planner can see referenced
    # event details (e.g. start/end times when user says "keep it the same").
    history_events = _history_events(payload.history)

    # ── Fast-path: execute a previously confirmed action ────────────────────
    # When the user says yes/confirm/ok in response to a confirmation message,
    # we skip LLM planning entirely and execute the pre-built body.
    if payload.pending_plan and payload.pending_plan.get("confirmed_body") is not None:
        msg_lower = payload.message.lower().strip()
        _CONFIRM_KWS = {"yes", "confirm", "confirmed", "ok", "sure", "proceed", "do it", "go ahead", "yep", "yeah", "yup", "correct", "fine"}
        # Cancel only when the message IS a cancellation — not when "no" appears inside a correction.
        # e.g. "no" → cancel; "no the one on april 1" → correction, not cancel.
        _STRICT_CANCEL = {"cancel", "cancelled", "abort", "stop", "skip", "nevermind", "never mind"}
        _msg_bare = msg_lower.rstrip('.!? ')
        _is_confirm = any(kw in msg_lower for kw in _CONFIRM_KWS)
        _is_cancel = (
            _msg_bare in _STRICT_CANCEL
            or _msg_bare in {"no", "nope", "don't"}  # standalone only
            or (len(payload.message.split()) <= 3 and _msg_bare.split()[0] in _STRICT_CANCEL)
        )
        if _is_confirm or _is_cancel:
            if _is_cancel:
                return {"answer": "Got it, cancelled.", "mode": "answer", "actions": [], "events": [], "plan": {}}
            pp = payload.pending_plan
            pp_action = pp.get("action", "")
            confirmed_body = pp.get("confirmed_body", {})
            cal_id = pp.get("confirmed_calendar_id", "")
            event_id = pp.get("confirmed_event_id", "")
            if pp_action == "update_event" and event_id and confirmed_body:
                try:
                    updated = update_event(creds, cal_id, event_id, confirmed_body)
                except HttpError as exc:
                    translate_google_api_error(exc)
                return {
                    "answer": _build_action_summary("update_event", updated, calendars),
                    "mode": "action",
                    "actions": [{"type": "update_event", "calendarId": updated.get("calendarId"), "eventId": updated.get("id")}],
                    "events": [updated],
                    "plan": {},
                }
            if pp_action == "delete_event" and event_id:
                event_for_resp = next((e for e in history_events if e.get("id") == event_id), {"id": event_id, "title": "event"})
                try:
                    delete_event(creds, cal_id, event_id)
                except HttpError as exc:
                    translate_google_api_error(exc)
                return {
                    "answer": _build_action_summary("delete_event", event_for_resp, calendars),
                    "mode": "action",
                    "actions": [{"type": "delete_event", "calendarId": cal_id, "eventId": event_id}],
                    "events": [],
                    "plan": {},
                }
    # ── End fast-path ────────────────────────────────────────────────────────

    try:
        plan = _plan_chat_action(
            payload.message, payload.history, history_events, calendars, sample_questions, client,
            pending_plan=payload.pending_plan,
        )
    except OllamaClientError as exc:
        raise HTTPException(status_code=503, detail={"message": str(exc)}) from exc

    action = plan.get("action", "answer")

    # ── Pending-plan override ────────────────────────────────────────────────
    # When the user is responding to a clarification (card tap or typed reply),
    # the frontend echoes back the pending_plan that was attached to the
    # clarification message.  We use it to restore the original action and
    # updates so they are never lost across turns.
    #
    # Guard: only apply when this message is genuinely a clarification reply.
    # A new unrelated query (e.g. "list my events") must NOT be hijacked by a
    # stale pending_plan.  We consider it a clarification reply when:
    #   (a) the planner itself returned update/delete (it understood the context), OR
    #   (b) the planner returned "answer" AND the raw message looks like a
    #       short confirmation / pronoun follow-up (not a fresh question).
    # Pending plans with confirmed_body are handled above (fast-path), so exclude them here.
    _has_confirmed_body = bool(payload.pending_plan and payload.pending_plan.get("confirmed_body") is not None)
    _is_clarification_reply = (
        not _has_confirmed_body
        and payload.pending_plan is not None
        and payload.selected_event_id is not None  # card tap — always a clarification reply
    ) or (
        not _has_confirmed_body
        and payload.pending_plan is not None
        and action in {"update_event", "delete_event"}  # planner already agreed
    ) or (
        not _has_confirmed_body
        and payload.pending_plan is not None
        and action == "answer"
        # Short messages without interrogative/listing keywords are likely
        # confirmation replies ("yes", "the one on Monday", "I mean X").
        and len(payload.message.split()) <= 15
        and not any(
            kw in payload.message.lower()
            for kw in ("how many", "list", "show", "what", "which", "when", "count", "do i have", "give me", "tell me")
        )
    )

    if _is_clarification_reply:
        pp = payload.pending_plan  # type: ignore[assignment]
        pp_action = pp.get("action", "")
        if pp_action in {"update_event", "delete_event"}:
            # Restore the mutation action the planner may have misclassified.
            action = pp_action
            plan["action"] = action
            plan["needs_clarification"] = False
            # Restore updates when the planner left them empty.
            plan_updates = plan.get("updates") or {}
            if not any(v for v in plan_updates.values() if v):
                plan["updates"] = pp.get("updates") or {}
            # Restore target_hint and time bounds when blank.
            if not plan.get("target_hint"):
                plan["target_hint"] = pp.get("target_hint") or ""
            if not plan.get("time_min"):
                plan["time_min"] = pp.get("time_min") or ""
            if not plan.get("time_max"):
                plan["time_max"] = pp.get("time_max") or ""
    # ── End pending-plan override ────────────────────────────────────────────

    if (
        action in {"update_event", "delete_event"}
        and not plan.get("target_hint")
        and _PRONOUN_RE.search(payload.message)
        and history_events
    ):
        last_title = history_events[-1].get("title", "")
        if last_title:
            plan["target_hint"] = last_title
            plan["search_query"] = last_title

    if action in {"update_event", "delete_event"} and plan.get("target_hint"):
        plan["search_query"] = plan["target_hint"]

    resolved_calendar_id = _resolve_calendar_id(
        plan.get("calendar_id"), calendars, _default_calendar_id(action, calendars)
    )

    if plan.get("needs_clarification"):
        # For update/delete: eagerly fetch the target event so it appears in
        # history.events on the follow-up turn.  We search both future and the
        # past 90 days so old events are not silently excluded.
        clarification_events: list[dict] = []
        if action in {"update_event", "delete_event"}:
            try:
                _now = datetime.now(UTC)
                prefetch_candidates, _ = fetch_all_events(
                    creds,
                    calendar_ids=[resolved_calendar_id]
                    if resolved_calendar_id and resolved_calendar_id != "all"
                    else None,
                    q=plan.get("target_hint") or None,
                    time_min=plan.get("time_min") or (_now - timedelta(days=180)).isoformat(),
                    time_max=plan.get("time_max") or (_now + timedelta(days=365)).isoformat(),
                )
                prefetch_target_tokens = _meaningful_tokens(
                    plan.get("target_hint") or plan.get("search_query") or ""
                )
                prefetch_history = (
                    [
                        event
                        for event in history_events
                        if prefetch_target_tokens
                        & _meaningful_tokens(event.get("title", ""))
                    ]
                    if prefetch_target_tokens
                    else history_events
                )
                target_prefetch, _ = _resolve_target_event(
                    payload.message,
                    plan,
                    _dedupe_events([*prefetch_history, *prefetch_candidates]),
                    calendars,
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
            "pending_plan": {
                "action": action,
                "updates": plan.get("updates") or {},
                "target_hint": plan.get("target_hint") or "",
                "time_min": plan.get("time_min") or "",
                "time_max": plan.get("time_max") or "",
                "calendar_id": resolved_calendar_id or "",
            } if action in {"update_event", "delete_event"} else None,
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

    # For update/delete apply a default lookback so past events are reachable.
    _fetch_time_min = plan.get("time_min") or None
    _fetch_time_max = plan.get("time_max") or None
    if action in {"update_event", "delete_event"}:
        now_utc = datetime.now(UTC)
        default_min = (now_utc - timedelta(days=180)).isoformat()
        default_max = (now_utc + timedelta(days=365)).isoformat()
        if not _fetch_time_min or _fetch_time_min > default_min:
            _fetch_time_min = default_min
        if not _fetch_time_max:
            _fetch_time_max = default_max

    if action == "answer":
        q_param = plan.get("search_query") or None
    elif action in {"update_event", "delete_event"} and plan.get("target_hint"):
        q_param = plan.get("target_hint")
    else:
        q_param = None

    try:
        candidate_events, scanned_calendar_ids = fetch_all_events(
            creds,
            calendar_ids=[resolved_calendar_id]
            if resolved_calendar_id and resolved_calendar_id != "all"
            else None,
            q=q_param,
            time_min=_fetch_time_min,
            time_max=_fetch_time_max,
        )
    except HttpError as exc:
        translate_google_api_error(exc)

    filtered_events = _filter_events(
        _dedupe_events([*history_events, *candidate_events]), plan
    )

    # Remove holiday/birthday calendar events when user asked, OR always for update/delete
    # (festival events like "Ramadan Start" should never be returned as update/delete targets).
    _holiday_calendar_ids = {
        cal["id"]
        for cal in calendars
        if cal.get("isHoliday") or cal.get("isBirthday")
    }
    if plan.get("exclude_holiday_calendars") or action in {"update_event", "delete_event"}:
        filtered_events = [
            event
            for event in filtered_events
            if event.get("calendarId") not in _holiday_calendar_ids
        ]
        if action in {"update_event", "delete_event"}:
            history_events = [
                event for event in history_events
                if event.get("calendarId") not in _holiday_calendar_ids
            ]

    if action == "answer":
        try:
            vs = get_vector_store()
            relevant_questions = vs.query_sample_questions(payload.message, top_k=6) if sample_questions else []
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
        target_tokens = _meaningful_tokens(
            plan.get("target_hint") or plan.get("search_query") or ""
        )
        relevant_history = (
            [
                event
                for event in history_events
                if target_tokens & _meaningful_tokens(event.get("title", ""))
            ]
            if target_tokens
            else history_events
        )
        all_candidates_pool = _dedupe_events([*relevant_history, *candidate_events])

        # If the previous assistant turn pinpointed exactly one event, use it directly.
        last_assistant_turn = next(
            (t for t in reversed(payload.history) if t.role == "assistant"),
            None,
        )
        clarification_target_id: Optional[str] = (
            last_assistant_turn.events[0].get("id")
            if last_assistant_turn and len(last_assistant_turn.events) == 1
            else None
        )
        try:
            target_event: Optional[dict] = None
            options: list[dict] = []

            # Priority 1: explicit card selection via selected_event_id
            if payload.selected_event_id:
                target_event = next(
                    (e for e in all_candidates_pool if e.get("id") == payload.selected_event_id),
                    None,
                )
                if target_event:
                    options = [target_event]

            # Priority 2: previous clarification pinpointed one event.
            # Skip when the user is correcting us ("no", "not", "I mean", "actually", etc.)
            # — in that case the user is re-identifying the event, not confirming the old one.
            _CORRECTION_STARTERS = ("no ", "no,", "not ", "i mean", "actually", "wait,", "wrong", "that's not", "thats not", "i said")
            _is_correction = any(payload.message.lower().startswith(s) for s in _CORRECTION_STARTERS) or payload.message.lower().strip() == "no"
            if not target_event and clarification_target_id and not _is_correction:
                target_event = next(
                    (e for e in filtered_events if e.get("id") == clarification_target_id),
                    None,
                ) or next(
                    (e for e in history_events if e.get("id") == clarification_target_id),
                    None,
                )
                if target_event:
                    options = [target_event]

            # Priority 3: fuzzy/semantic resolution
            if not target_event:
                target_event, options = _resolve_target_event(
                    payload.message, plan, filtered_events, calendars
                )
        except OllamaClientError as exc:
            raise HTTPException(status_code=503, detail={"message": str(exc)}) from exc

        if not target_event:
            shown_options = options[:3]
            n = len(shown_options)
            if n > 1:
                msg = (
                    f"I found {n} possible matches. Tap the correct event:"
                )
            elif n == 1:
                msg = "Found one possible match — tap it to proceed:"
            else:
                msg = (
                    "I couldn't find a matching event. "
                    "Please check the event title and try again."
                )
            return {
                "answer": msg,
                "mode": "clarification",
                "actions": [],
                "events": shown_options,
                "plan": plan,
                "pending_plan": {
                    "action": action,
                    "updates": plan.get("updates") or {},
                    "target_hint": plan.get("target_hint") or "",
                    "time_min": plan.get("time_min") or "",
                    "time_max": plan.get("time_max") or "",
                    "calendar_id": resolved_calendar_id or "",
                },
            }

        # ── Delete: always confirm before executing ──────────────────────────
        if action == "delete_event":
            return {
                "answer": _build_confirmation_message("delete_event", target_event, {}),
                "mode": "confirmation",
                "actions": [],
                "events": [target_event],
                "plan": plan,
                "pending_plan": {
                    "action": "delete_event",
                    "confirmed_event_id": target_event["id"],
                    "confirmed_calendar_id": target_event["calendarId"],
                    "confirmed_body": {},
                },
            }

        # ── Update: build body, then confirm or execute ──────────────────────
        update_payload = plan.get("updates") or {}
        if not any(v for v in update_payload.values() if v):
            # No updates extracted — ask what to change (keep event in context)
            return {
                "answer": f"What would you like to change about '{target_event.get('title')}'? "
                          "(e.g. new date, time, title, location)",
                "mode": "clarification",
                "actions": [],
                "events": [target_event],
                "plan": plan,
                "pending_plan": {
                    "action": "update_event",
                    "updates": {},
                    "target_hint": target_event.get("title", ""),
                    "time_min": "",
                    "time_max": "",
                    "calendar_id": target_event.get("calendarId", ""),
                },
            }

        body = _build_event_body(update_payload, existing_event=target_event)
        if not body:
            return {
                "answer": f"I couldn't extract valid changes from your request for '{target_event.get('title')}'. "
                          "Please specify a new date, time, or other field.",
                "mode": "clarification",
                "actions": [],
                "events": [target_event],
                "plan": plan,
            }

        # Card-tap (user explicitly selected this event): execute directly.
        # Text match (bot inferred the event): show confirmation first.
        if payload.selected_event_id:
            try:
                updated = update_event(creds, target_event["calendarId"], target_event["id"], body)
            except HttpError as exc:
                translate_google_api_error(exc)
            return {
                "answer": _build_action_summary("update_event", updated, calendars),
                "mode": "action",
                "actions": [{"type": "update_event", "calendarId": updated.get("calendarId"), "eventId": updated.get("id")}],
                "events": [updated],
                "plan": plan,
            }

        return {
            "answer": _build_confirmation_message("update_event", target_event, body),
            "mode": "confirmation",
            "actions": [],
            "events": [target_event],
            "plan": plan,
            "pending_plan": {
                "action": "update_event",
                "confirmed_event_id": target_event["id"],
                "confirmed_calendar_id": target_event["calendarId"],
                "confirmed_body": body,
            },
        }

    return {
        "answer": "I could not determine how to handle that request yet.",
        "mode": "clarification",
        "actions": [],
        "events": [],
        "plan": plan,
    }
