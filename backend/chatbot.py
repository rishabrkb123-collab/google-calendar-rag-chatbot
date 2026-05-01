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
from backend.vector_store import get_vector_store
from googleapiclient.errors import HttpError


router = APIRouter(prefix="/chat")


def _build_llm_client():
    cfg = get_ollama_config()
    return OllamaClient(
        base_url=cfg["base_url"],
        chat_model=cfg["chat_model"],
        api_key=cfg["api_key"],
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

GENERIC_TARGET_TOKENS = {
    "appointment",
    "appointmnt",
    "booking",
    "check",
    "checkup",
    "event",
    "general",
    "meeting",
    "reminder",
    "routine",
    "schedule",
}

_PRONOUN_RE = re.compile(
    r"\b(it|this|that|the same one?|that one|the event|that event|this event)\b",
    re.IGNORECASE,
)
_DELETE_ACTION_RE = re.compile(
    r"\b(cancel|cancelled|delete|deleted|remove|removed|drop|dropped)\b",
    re.IGNORECASE,
)
_UPDATE_ACTION_RE = re.compile(
    r"\b(update|updated|move|moved|reschedule|rescheduled|change|changed|edit|edited|modify|modified|shift|shifted|rename|renamed|postpone|postponed|delay|delayed)\b",
    re.IGNORECASE,
)
_CREATE_ACTION_RE = re.compile(
    r"\b(create|created|schedule|scheduled|book|booked|add|added|set up|make|made)\b",
    re.IGNORECASE,
)
_ANSWER_ACTION_RE = re.compile(
    r"\b(what|when|which|who|list|show|find|search|count|availability|available|am i free|do i have|free slot|free time)\b",
    re.IGNORECASE,
)
_FIELD_REPLY_RE = re.compile(
    r"\b(date|day|time|timing|timings|title|name|location|place|description|details)\b",
    re.IGNORECASE,
)
_SAME_TIME_RE = re.compile(
    r"\b(same time|same timing|same timings|keep (?:it )?the same time|with the same time)\b",
    re.IGNORECASE,
)
_MONTH_NAME_LOOKUP = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_WEEKDAY_LOOKUP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_CORRECTION_STARTERS = (
    "no ",
    "no,",
    "not ",
    "i mean",
    "actually",
    "wait",
    "wrong",
    "that's not",
    "thats not",
    "i said",
)
_FOLLOW_UP_CONFIRM_KWS = {
    "yes",
    "ok",
    "okay",
    "confirm",
    "confirmed",
    "sure",
    "correct",
    "go ahead",
    "do it",
    "yep",
    "yeah",
    "yup",
}
_FOLLOW_UP_CANCEL_KWS = {
    "cancel",
    "cancelled",
    "abort",
    "stop",
    "skip",
    "nevermind",
    "never mind",
    "no",
    "nope",
}

ACTION_SAMPLE_GROUPS = ("create_event", "update_event", "delete_event")


class ChatTurn(BaseModel):
    role: str
    content: str
    events: list[dict] = Field(default_factory=list)
    mode: Optional[str] = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    history: list[ChatTurn] = Field(default_factory=list)
    # When the user taps a suggested event card in the UI, the frontend passes
    # the event's ID here so the backend can skip fuzzy matching entirely.
    selected_event_id: Optional[str] = None
    selected_calendar_id: Optional[str] = None
    # The frontend echoes the pending_plan from the last clarification response
    # so the original action + updates survive across clarification turns.
    pending_plan: Optional[dict] = None


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _meaningful_tokens(text: str) -> set[str]:
    return {
        token for token in _tokenize(text) if token not in STOPWORDS and len(token) > 1
    }


def _distinctive_tokens(text: str) -> set[str]:
    return {
        token for token in _meaningful_tokens(text) if token not in GENERIC_TARGET_TOKENS
    }


def _is_generic_target_text(text: str) -> bool:
    normalized = text.strip().lower()
    if _PRONOUN_RE.fullmatch(normalized):
        return True
    tokens = _meaningful_tokens(text)
    if not tokens:
        return True
    return not any(token not in GENERIC_TARGET_TOKENS for token in tokens)


def _message_starts_with_correction(message: str) -> bool:
    lowered = message.lower().strip()
    return lowered == "no" or any(lowered.startswith(prefix) for prefix in _CORRECTION_STARTERS)


def _likely_follow_up_message(
    message: str,
    pending_plan: Optional[dict],
    selected_event_id: Optional[str] = None,
) -> bool:
    if not pending_plan or pending_plan.get("action") not in {"update_event", "delete_event"}:
        return False
    if selected_event_id:
        return True

    lowered = message.lower().strip()
    if not lowered:
        return False
    if lowered in _FOLLOW_UP_CONFIRM_KWS or lowered in _FOLLOW_UP_CANCEL_KWS:
        return True
    if _message_starts_with_correction(message):
        return True
    if _PRONOUN_RE.search(message) or _FIELD_REPLY_RE.search(message) or _SAME_TIME_RE.search(message):
        return True

    inferred_action = _infer_requested_action(message)
    if inferred_action == "create_event":
        return False
    if inferred_action == "answer" and (
        message.strip().endswith("?") or _ANSWER_ACTION_RE.search(message)
    ):
        return False
    if inferred_action == pending_plan.get("action"):
        return True
    return len(message.split()) <= 12


def _clean_capture(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" \t\n\r\"'.,:;-")


def _extract_explicit_date(message: str, now: Optional[datetime] = None) -> Optional[date]:
    reference = (now or datetime.now().astimezone()).date()
    lowered = message.lower()

    if re.search(r"\btoday\b", lowered):
        return reference
    if re.search(r"\btomorrow\b", lowered):
        return reference + timedelta(days=1)

    next_weekday_match = re.search(
        r"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        lowered,
    )
    if next_weekday_match:
        weekday = _WEEKDAY_LOOKUP[next_weekday_match.group(1)]
        days_ahead = (weekday - reference.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return reference + timedelta(days=days_ahead)

    for pattern in (
        re.compile(
            r"\b(january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug|september|sept|sep|october|oct|november|nov|december|dec)\s+(\d{1,2})(?:st|nd|rd|th)?\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug|september|sept|sep|october|oct|november|nov|december|dec)\b",
            re.IGNORECASE,
        ),
    ):
        match = pattern.search(message)
        if not match:
            continue
        if match.re.pattern.startswith("\\b(january"):
            month_name, day_value = match.group(1), match.group(2)
        else:
            day_value, month_name = match.group(1), match.group(2)
        month = _MONTH_NAME_LOOKUP[month_name.lower()]
        day = int(day_value)
        candidate = date(reference.year, month, day)
        if candidate < reference - timedelta(days=1):
            candidate = date(reference.year + 1, month, day)
        return candidate

    return None


def _extract_explicit_time(message: str) -> Optional[tuple[int, int]]:
    twelve_hour = re.search(
        r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
        message,
        re.IGNORECASE,
    )
    if twelve_hour:
        hour = int(twelve_hour.group(1)) % 12
        minute = int(twelve_hour.group(2) or 0)
        meridiem = twelve_hour.group(3).lower()
        if meridiem == "pm":
            hour += 12
        return hour, minute

    twenty_four_hour = re.search(r"\b(?:at\s+)?([01]?\d|2[0-3]):([0-5]\d)\b", message)
    if twenty_four_hour:
        return int(twenty_four_hour.group(1)), int(twenty_four_hour.group(2))
    return None


def _combine_date_and_time(
    date_value: date,
    time_value: tuple[int, int],
    reference_tz,
) -> str:
    tzinfo = reference_tz or datetime.now().astimezone().tzinfo
    return datetime.combine(
        date_value,
        datetime.min.time().replace(hour=time_value[0], minute=time_value[1]),
        tzinfo=tzinfo,
    ).isoformat()


def _extract_create_title(message: str) -> str:
    patterns = [
        re.compile(
            r"\bfor\s+(.+?)(?=\s+(?:on|at|tomorrow|today|next)\b|$)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:called|named|titled)\s+(.+?)(?=\s+(?:on|at|tomorrow|today|next)\b|$)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:create|schedule|book|add|set up|make)\s+(?:an?\s+)?(?:event|appointment|meeting|reminder)?\s*(.+?)(?=\s+(?:on|at|tomorrow|today|next)\b|$)",
            re.IGNORECASE,
        ),
    ]
    for pattern in patterns:
        match = pattern.search(message)
        if not match:
            continue
        title = _clean_capture(match.group(1))
        lowered = title.lower()
        if lowered in GENERIC_TARGET_TOKENS or not re.search(r"[a-z]", lowered):
            continue
        return title
    return ""


def _merge_sparse_payload(existing: dict[str, Any], repairs: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in repairs.items():
        if value in (None, "", []):
            continue
        current = merged.get(key)
        if current in (None, "", []):
            merged[key] = value
        elif isinstance(value, bool) and not current:
            merged[key] = value
    return merged


def _repair_create_payload(message: str, existing_payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(existing_payload)
    now = datetime.now().astimezone()
    parsed_date = _extract_explicit_date(message, now=now)
    parsed_time = _extract_explicit_time(message)

    repairs: dict[str, Any] = {}
    if not payload.get("title"):
        title = _extract_create_title(message)
        if title:
            repairs["title"] = title

    if not payload.get("start") and parsed_date:
        if parsed_time:
            repairs["start"] = _combine_date_and_time(parsed_date, parsed_time, now.tzinfo)
        else:
            repairs["start"] = parsed_date.isoformat()

    return _merge_sparse_payload(payload, repairs)


def _repair_update_payload(message: str, existing_payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(existing_payload)
    now = datetime.now().astimezone()
    parsed_date = _extract_explicit_date(message, now=now)
    parsed_time = _extract_explicit_time(message)

    repairs: dict[str, Any] = {}
    if not payload.get("start") and parsed_date:
        if parsed_time:
            repairs["start"] = _combine_date_and_time(parsed_date, parsed_time, now.tzinfo)
        else:
            repairs["start"] = parsed_date.isoformat()
    elif payload.get("start") and "T" not in str(payload.get("start")) and parsed_time:
        repairs["start"] = _combine_date_and_time(
            date.fromisoformat(str(payload["start"])[:10]),
            parsed_time,
            now.tzinfo,
        )

    if not payload.get("title"):
        rename_match = re.search(
            r"\b(?:rename|change\s+title\s+to|update\s+title\s+to)\s+(.+)$",
            message,
            re.IGNORECASE,
        )
        if rename_match:
            repairs["title"] = _clean_capture(rename_match.group(1))

    if not payload.get("location"):
        location_match = re.search(
            r"\b(?:move|change|update)\s+(?:the\s+)?location\s+to\s+(.+)$",
            message,
            re.IGNORECASE,
        )
        if location_match:
            repairs["location"] = _clean_capture(location_match.group(1))

    return _merge_sparse_payload(payload, repairs)


def _repair_plan(message: str, plan: dict[str, Any]) -> dict[str, Any]:
    action = plan.get("action") or _infer_requested_action(message)
    plan["action"] = action

    for field in ("target_hint", "search_query", "calendar_id"):
        value = plan.get(field)
        if isinstance(value, str):
            plan[field] = _clean_capture(value)

    if action in {"update_event", "delete_event"}:
        extracted_target = _extract_target_hint_from_message(message)
        if extracted_target and not plan.get("target_hint"):
            plan["target_hint"] = extracted_target
        if plan.get("target_hint"):
            plan["search_query"] = plan["target_hint"]

    if action == "create_event":
        repaired_event = _repair_create_payload(message, plan.get("event") or {})
        if repaired_event:
            plan["event"] = repaired_event
        if repaired_event.get("title") and repaired_event.get("start"):
            plan["needs_clarification"] = False
            plan["clarification_question"] = ""
            if not plan.get("search_query"):
                plan["search_query"] = repaired_event["title"]

    if action == "update_event":
        repaired_updates = _repair_update_payload(message, plan.get("updates") or {})
        if repaired_updates:
            plan["updates"] = repaired_updates
        if any(value for value in repaired_updates.values() if value not in (False, [], "", None)):
            plan["needs_clarification"] = False
            plan["clarification_question"] = ""

    return plan


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


def _format_event_context_line(event: dict, calendar_lookup: dict[str, dict]) -> str:
    calendar_id = event.get("calendarId", "primary")
    calendar_name = calendar_lookup.get(calendar_id, {}).get("name", calendar_id)
    start = (
        event.get("start", {}).get("dateTime")
        or event.get("start", {}).get("date")
        or ""
    )
    end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date") or ""
    attendee_names = []
    for attendee in event.get("attendees", []):
        attendee_name = attendee.get("displayName") or attendee.get("email", "")
        if attendee_name:
            attendee_names.append(attendee_name)
    description = (event.get("description") or "").strip().replace("\n", " ")
    parts = [
        f"id={event.get('id', '')}",
        f"calendar_id={calendar_id}",
        f"calendar_name={calendar_name}",
        f"title={event.get('title', '(No title)')}",
    ]
    if start:
        parts.append(f"start={start}")
    if end:
        parts.append(f"end={end}")
    if event.get("location"):
        parts.append(f"location={event.get('location')}")
    if attendee_names:
        parts.append(f"attendees={', '.join(attendee_names[:8])}")
    if description:
        parts.append(f"description={description[:220]}")
    return " | ".join(parts)


def _event_match_text(event: dict) -> str:
    attendee_parts = []
    for attendee in event.get("attendees", []):
        display_name = attendee.get("displayName") or attendee.get("email", "").split("@")[0]
        if display_name:
            attendee_parts.append(display_name)
    start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date", "")
    end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date", "")
    parts = [
        event.get("title", ""),
        start,
        end,
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
    """Best-effort extraction of an existing event name from common mutation phrasings."""
    normalized_message = message.strip()

    quoted_match = re.search(r"['\"]([^'\"]{2,200})['\"]", normalized_message)
    if quoted_match:
        quoted_target = _clean_capture(quoted_match.group(1))
        if quoted_target and not _is_generic_target_text(quoted_target):
            return quoted_target

    patterns = [
        re.compile(
            r"(?:delete|deleted|remove|removed|cancel|cancelled|update|updated|change|changed|move|moved|reschedule|rescheduled|edit|edited|modify|modified|shift|shifted|rename|renamed|postpone|postponed|delay|delayed)\s+"
            r"(?:my\s+|the\s+|an?\s+)?(['\"]?)(.+?)\1"
            r"\s*(?:appointment|event|meeting|schedule|reminder)?(?:\s+(?:from|to|on|at|by)\b.*)?$",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:i\s+want\s+)?(?:my\s+|the\s+)?(['\"]?)(.+?)\1"
            r"\s*(?:appointment|event|meeting|schedule|reminder)?\s+to\s+be\s+"
            r"(?:update|updated|move|moved|reschedule|rescheduled|change|changed|edit|edited|modify|modified|shift|shifted|rename|renamed|postpone|postponed|delay|delayed)\b(?:\s+(?:from|to|on|at|by)\b.*)?$",
            re.IGNORECASE,
        ),
    ]
    for pattern in patterns:
        match = pattern.search(normalized_message)
        if not match:
            continue
        name = _clean_capture(match.group(2))
        if name and not _is_generic_target_text(name):
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
        "Return ONLY raw JSON — no prose, no markdown, no explanation whatsoever.\n\n"
        "ACTION SELECTION:\n"
        "  answer       — user wants info, list, count, or search events\n"
        "  create_event — user wants to ADD / BOOK / SCHEDULE a NEW event\n"
        "  update_event — user wants to MOVE / SHIFT / RESCHEDULE / CHANGE / RENAME / EDIT an existing event\n"
        "  delete_event — user wants to REMOVE / CANCEL / DELETE an existing event\n\n"
        "CREATE EVENT — fill the 'event' field (REQUIRED for create_event):\n"
        "  'book appointment June 13 at 5pm for General Dental Checkup'\n"
        "    → action='create_event', event.title='General Dental Checkup', event.start='2026-06-13T17:00:00+05:30'\n"
        "  'schedule standup tomorrow at 10am'\n"
        "    → action='create_event', event.title='Standup', event.start=[tomorrow ISO datetime]\n"
        "  Rule: if user says book/schedule/add/create + title + date/time → action=create_event, populate event field, needs_clarification=false.\n\n"
        "UPDATE EVENT — fill the 'updates' field (REQUIRED for update_event):\n"
        "  'shift dental checkup to June 12 with same timing'\n"
        "    → action='update_event', target_hint='dental checkup', updates.start='2026-06-12', needs_clarification=false\n"
        "  'move meeting to June 12 at 3pm'\n"
        "    → action='update_event', updates.start='2026-06-12T15:00:00+05:30', needs_clarification=false\n"
        "  'rename dentist to teeth cleaning'\n"
        "    → action='update_event', updates.title='Teeth Cleaning', needs_clarification=false\n"
        "  'change location to City Hospital'\n"
        "    → action='update_event', updates.location='City Hospital', needs_clarification=false\n"
        "  SAME TIME RULE: 'same time / same timing / same timings' alongside a new date → updates.start='YYYY-MM-DD' (date only, NO time part). Backend preserves the original time automatically.\n"
        "  ALWAYS set search_query = target_hint for update/delete.\n\n"
        "DATETIME RULES:\n"
        "  - Use CURRENT_DATETIME to resolve relative dates: 'tomorrow', 'next Monday', 'June 12' etc.\n"
        "  - Timed events: ISO 8601 with timezone offset (e.g. 2026-06-13T17:00:00+05:30).\n"
        "  - All-day or date-only updates: YYYY-MM-DD.\n"
        "  - Recurring: RRULE string (e.g. RRULE:FREQ=WEEKLY;BYDAY=MO).\n\n"
        "needs_clarification RULES — set true ONLY when a truly required field is completely absent:\n"
        "  DO NOT set needs_clarification=true when:\n"
        "    - User gives event name + new date (even without exact time) → extract date, set needs_clarification=false\n"
        "    - User says 'same time/timing/timings' → set updates.start=YYYY-MM-DD, needs_clarification=false\n"
        "    - User says yes/ok/correct/confirm → needs_clarification=false\n"
        "    - Event can be inferred from RECENT_HISTORY or HISTORY_EVENTS → needs_clarification=false\n"
        "    - User says book/schedule + title + date → create_event, needs_clarification=false\n"
        "  When truly needed: ask ONE short specific question.\n\n"
        "OTHER RULES:\n"
        "  all_time=true ONLY for 'all time / ever / all events ever'.\n"
        "  list_all=true for 'list all / show everything / count all'.\n"
        "  exclude_holiday_calendars=true only when user explicitly says so.\n"
        "  Target name pattern: '[action] [NAME] appointment/event/meeting' → target_hint=NAME.\n"
        "  Pronoun rule: 'this'/'it'/'that event' → resolve from HISTORY_EVENTS, set target_hint to its title.\n"
        "  Correction rule: message starts with 'no/not/I mean/actually/wait' → new target identification, keep action, needs_clarification=false.\n"
        "  Clarification follow-up: RECENT_HISTORY shows assistant asked → user reply IS the answer, keep action, do NOT ask again.\n"
        "  Fresh request rule: if USER_MESSAGE clearly asks to create/book/schedule a NEW event, set action=create_event and ignore any unrelated older context.\n"
        "  Never ask what to change when the user already gave a new date, time, title, or location."
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
        return _repair_plan(request_message, _fallback_plan(request_message, calendars))

    if not isinstance(plan, dict) or not plan.get("action"):
        return _repair_plan(request_message, _fallback_plan(request_message, calendars))
    return _repair_plan(request_message, plan)


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
    distinctive_query_tokens = _distinctive_tokens(query)
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
            distinctive_overlap = len(distinctive_query_tokens & match_tokens)
            if distinctive_query_tokens and distinctive_overlap == 0:
                continue
            if overlap:
                lexical_matches.append((event, distinctive_overlap, overlap))

        lexical_matches.sort(key=lambda item: (item[1], item[2]), reverse=True)
        if lexical_matches:
            top_distinctive_overlap = lexical_matches[0][1]
            top_overlap = lexical_matches[0][2]
            strongest_matches = [
                event
                for event, distinctive_overlap, overlap in lexical_matches
                if distinctive_overlap == top_distinctive_overlap and overlap == top_overlap
            ]
            if (
                len(strongest_matches) == 1
                and (
                    (distinctive_query_tokens and top_distinctive_overlap >= 1)
                    or top_overlap >= 2
                    or len(query_tokens) == 1
                )
            ):
                return strongest_matches[0], strongest_matches
            if strongest_matches:
                matched_event, ranked_options = _select_ranked_event(
                    query, strongest_matches, calendar_lookup
                )
                if matched_event:
                    return matched_event, strongest_matches
                if ranked_options:
                    return None, ranked_options

    semantic_candidates = events
    if distinctive_query_tokens:
        semantic_candidates = [
            event
            for event in events
            if distinctive_query_tokens & _meaningful_tokens(_event_match_text(event))
        ]
        if not semantic_candidates:
            return None, []

    return _select_ranked_event(query, semantic_candidates, calendar_lookup)


def _resolve_target_event_with_llm(
    request_message: str,
    plan: dict[str, Any],
    events: list[dict],
    calendars: list[dict],
    client: OllamaClient,
) -> tuple[Optional[dict], list[dict]]:
    if not events:
        return None, []

    calendar_lookup = {calendar["id"]: calendar for calendar in calendars}
    event_lookup = {
        (event.get("calendarId", "primary"), event.get("id", "")): event
        for event in events
    }
    event_lines = "\n".join(
        f"- {_format_event_context_line(event, calendar_lookup)}" for event in events
    )
    query_context = {
        key: plan.get(key)
        for key in ("action", "search_query", "target_hint", "time_min", "time_max")
        if plan.get(key)
    }
    system_prompt = (
        "You are the event disambiguation layer of a Google Calendar assistant. "
        "Your only job is to identify which existing calendar event the user is referring to. "
        "You must choose ONLY from the ALL_EVENTS list provided and return strict JSON only. "
        "Rules:\n"
        "  - Never invent an event, title, ID, or calendar.\n"
        "  - Prefer the strongest match based on title, date, time, attendee, location, and description.\n"
        "  - If one event is clearly the best match, set ambiguous=false and confidence=high or medium.\n"
        "  - If multiple events remain plausible, set ambiguous=true and return up to 3 candidate_event_ids.\n"
        "  - If nothing matches, leave selected_event_id empty and return ambiguous=true.\n"
        "Return JSON with this shape:\n"
        '{'
        '"selected_event_id": "", '
        '"selected_calendar_id": "", '
        '"confidence": "high|medium|low", '
        '"ambiguous": false, '
        '"candidate_event_ids": []'
        '}'
    )
    user_prompt = (
        f"CURRENT_DATETIME: {datetime.now().astimezone().isoformat()}\n"
        f"USER_MESSAGE: {request_message}\n\n"
        f"QUERY_CONTEXT:\n{query_context}\n\n"
        f"ALL_EVENTS:\n{event_lines}"
    )

    try:
        decision = client.chat_json(system_prompt, user_prompt)
    except OllamaClientError:
        return None, []

    if not isinstance(decision, dict):
        return None, []

    selected_event: Optional[dict] = None
    selected_event_id = str(decision.get("selected_event_id") or "").strip()
    selected_calendar_id = str(decision.get("selected_calendar_id") or "").strip()
    if selected_event_id and selected_calendar_id:
        selected_event = event_lookup.get((selected_calendar_id, selected_event_id))
    if not selected_event and selected_event_id:
        selected_event = next(
            (event for event in events if event.get("id") == selected_event_id),
            None,
        )

    raw_candidate_ids = decision.get("candidate_event_ids") or []
    if isinstance(raw_candidate_ids, str):
        raw_candidate_ids = [raw_candidate_ids]
    option_ids = [
        str(candidate_id).strip()
        for candidate_id in raw_candidate_ids
        if str(candidate_id).strip()
    ]
    options = [
        event for event in events if event.get("id") in option_ids
    ]
    if selected_event and all(
        option.get("id") != selected_event.get("id") for option in options
    ):
        options = [selected_event, *options]

    confidence = str(decision.get("confidence") or "").strip().lower()
    ambiguous = bool(decision.get("ambiguous"))
    if selected_event and not ambiguous and confidence in {"high", "medium"}:
        return selected_event, options or [selected_event]

    return None, options[:3]


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

    return {
        "status": "ok",
        "llm": {
            "base_url": get_ollama_config()["base_url"],
            "chat_model": get_ollama_config()["chat_model"],
            "api_key_loaded": bool(get_ollama_config()["api_key"]),
        },
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
    active_pending_plan = (
        payload.pending_plan
        if _likely_follow_up_message(
            payload.message,
            payload.pending_plan,
            selected_event_id=payload.selected_event_id,
        )
        else None
    )

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
            pending_plan=active_pending_plan,
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
        and active_pending_plan is not None
        and payload.selected_event_id is not None  # card tap — always a clarification reply
    ) or (
        not _has_confirmed_body
        and active_pending_plan is not None
        and action in {"update_event", "delete_event"}  # planner already agreed
    ) or (
        not _has_confirmed_body
        and active_pending_plan is not None
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
        pp = active_pending_plan  # type: ignore[assignment]
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

    if action == "update_event":
        plan["updates"] = _repair_update_payload(
            payload.message, plan.get("updates") or {}
        )

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

    if action in {"update_event", "delete_event"} and q_param and not candidate_events:
        try:
            broad_candidate_events, broad_scanned_calendar_ids = fetch_all_events(
                creds,
                calendar_ids=[resolved_calendar_id]
                if resolved_calendar_id and resolved_calendar_id != "all"
                else None,
                q=None,
                time_min=_fetch_time_min,
                time_max=_fetch_time_max,
            )
        except HttpError as exc:
            translate_google_api_error(exc)
        candidate_events = _dedupe_events([*candidate_events, *broad_candidate_events])
        scanned_calendar_ids = broad_scanned_calendar_ids

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
            if last_assistant_turn
            and last_assistant_turn.mode == "clarification"
            and len(last_assistant_turn.events) == 1
            else None
        )
        try:
            target_event: Optional[dict] = None
            options: list[dict] = []

            # Priority 1: explicit card selection via selected_event_id
            if payload.selected_event_id:
                target_event = next(
                    (
                        e
                        for e in all_candidates_pool
                        if e.get("id") == payload.selected_event_id
                        and (
                            not payload.selected_calendar_id
                            or e.get("calendarId") == payload.selected_calendar_id
                        )
                    ),
                    None,
                )
                if not target_event:
                    target_event = next(
                        (e for e in all_candidates_pool if e.get("id") == payload.selected_event_id),
                        None,
                    )
                if target_event:
                    options = [target_event]

            # Priority 2: previous clarification pinpointed one event.
            # Skip when the user is correcting us ("no", "not", "I mean", "actually", etc.)
            # — in that case the user is re-identifying the event, not confirming the old one.
            _is_correction = _message_starts_with_correction(payload.message)
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
            if not target_event:
                llm_target_event, llm_options = _resolve_target_event_with_llm(
                    payload.message,
                    plan,
                    all_candidates_pool,
                    calendars,
                    client,
                )
                if llm_target_event:
                    target_event = llm_target_event
                    options = [llm_target_event]
                elif llm_options:
                    options = _dedupe_events([*llm_options, *options])
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
