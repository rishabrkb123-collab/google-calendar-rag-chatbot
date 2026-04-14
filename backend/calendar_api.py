import json
from datetime import date
from typing import Optional, Tuple

from fastapi import HTTPException
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.config import get_google_oauth_config


def build_credentials(tokens: dict) -> Credentials:
    oauth_config = get_google_oauth_config()
    creds = Credentials(
        token=tokens["token"],
        refresh_token=tokens.get("refresh_token"),
        token_uri=tokens.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=tokens.get("client_id", oauth_config["client_id"]),
        client_secret=tokens.get("client_secret", oauth_config["client_secret"]),
        scopes=tokens.get("scopes"),
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def serialize_event(event: dict, calendar_id: str) -> dict:
    return {
        "id": event.get("id"),
        "calendarId": calendar_id,
        "title": event.get("summary", "(No title)"),
        "start": event.get("start", {}),
        "end": event.get("end", {}),
        "description": event.get("description", ""),
        "location": event.get("location", ""),
        "organizer": event.get("organizer", {}).get("email", ""),
        "link": event.get("htmlLink", ""),
        "colorId": event.get("colorId"),
        "visibility": event.get("visibility", "default"),
        "attendees": event.get("attendees", []),
        "reminders": event.get("reminders"),
        "recurrence": event.get("recurrence", []),
        "allDay": "date" in event.get("start", {}),
    }


def translate_google_api_error(exc: HttpError) -> HTTPException:
    status_code = getattr(exc.resp, "status", 500) or 500
    message = "Google Calendar request failed."
    reason = None
    setup_url = None

    try:
        payload = json.loads(exc.content.decode("utf-8"))
        error = payload.get("error", {})
        errors = error.get("errors", [])
        primary = errors[0] if errors else {}
        message = primary.get("message") or error.get("message") or message
        reason = primary.get("reason")
        setup_url = primary.get("extendedHelp")
    except (
        AttributeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        message = str(exc) or message

    detail = {
        "code": "google_calendar_api_error",
        "message": message,
        "reason": reason,
        "status": status_code,
    }

    if reason == "accessNotConfigured":
        detail.update(
            {
                "code": "google_calendar_api_not_enabled",
                "message": "Google Calendar API is disabled for the current Google Cloud project.",
                "resolution": "Enable the Google Calendar API in Google Cloud Console for this OAuth project, wait a few minutes, then sign in again.",
                "setupUrl": setup_url,
            }
        )

    raise HTTPException(status_code=status_code, detail=detail)


def list_calendars(credentials: Credentials) -> list:
    service = build("calendar", "v3", credentials=credentials)
    result = service.calendarList().list().execute()
    return [
        {
            "id": cal["id"],
            "name": cal.get("summary", ""),
            "color": cal.get("backgroundColor", "#4285F4"),
            "primary": bool(cal.get("primary")),
            "readOnly": cal.get("accessRole") == "reader",
            "isHoliday": "holiday.calendar.google.com" in cal.get("id", "").lower()
            or "holiday" in cal.get("summary", "").lower(),
            "isBirthday": "contacts@group.v.calendar.google.com"
            in cal.get("id", "").lower()
            or "birthday" in cal.get("summary", "").lower(),
        }
        for cal in result.get("items", [])
    ]


def fetch_events(
    credentials: Credentials,
    calendar_id: str = "primary",
    q: Optional[str] = None,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    max_results: int = 250,
    page_token: Optional[str] = None,
) -> Tuple[list, Optional[str]]:
    service = build("calendar", "v3", credentials=credentials)
    params = {
        "calendarId": calendar_id,
        "maxResults": max_results,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    if q:
        params["q"] = q
    if time_min:
        params["timeMin"] = time_min
    if time_max:
        params["timeMax"] = time_max
    if page_token:
        params["pageToken"] = page_token

    result = service.events().list(**params).execute()
    events = [serialize_event(event, calendar_id) for event in result.get("items", [])]
    return events, result.get("nextPageToken")


def fetch_all_events(
    credentials: Credentials,
    calendar_ids: Optional[list[str]] = None,
    q: Optional[str] = None,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    max_results: int = 250,
) -> tuple[list, list[str]]:
    selected_calendar_ids = calendar_ids or [
        calendar["id"] for calendar in list_calendars(credentials)
    ]
    all_events: list[dict] = []

    for calendar_id in selected_calendar_ids:
        scoped_time_min = time_min
        scoped_time_max = time_max
        if not scoped_time_min and not scoped_time_max:
            lowered_calendar_id = calendar_id.lower()
            if (
                "holiday.calendar.google.com" in lowered_calendar_id
                or "holiday@group.v.calendar.google.com" in lowered_calendar_id
                or "contacts@group.v.calendar.google.com" in lowered_calendar_id
            ):
                current_year = date.today().year
                scoped_time_min = f"{current_year - 1}-01-01T00:00:00+00:00"
                scoped_time_max = f"{current_year + 1}-12-31T23:59:59+00:00"

        page_token = None
        while True:
            events, next_token = fetch_events(
                credentials,
                calendar_id=calendar_id,
                q=q,
                time_min=scoped_time_min,
                time_max=scoped_time_max,
                max_results=max_results,
                page_token=page_token,
            )
            all_events.extend(events)
            if not next_token:
                break
            page_token = next_token

    all_events.sort(
        key=lambda event: (
            event.get("start", {}).get("dateTime")
            or event.get("start", {}).get("date")
            or ""
        )
    )
    return all_events, selected_calendar_ids


def get_event(credentials: Credentials, calendar_id: str, event_id: str) -> dict:
    service = build("calendar", "v3", credentials=credentials)
    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
    return serialize_event(event, calendar_id)


def create_event(credentials: Credentials, calendar_id: str, body: dict) -> dict:
    service = build("calendar", "v3", credentials=credentials)
    event = service.events().insert(calendarId=calendar_id, body=body).execute()
    return serialize_event(event, calendar_id)


def update_event(
    credentials: Credentials, calendar_id: str, event_id: str, body: dict
) -> dict:
    service = build("calendar", "v3", credentials=credentials)
    event = (
        service.events()
        .patch(
            calendarId=calendar_id,
            eventId=event_id,
            body=body,
        )
        .execute()
    )
    return serialize_event(event, calendar_id)


def delete_event(credentials: Credentials, calendar_id: str, event_id: str) -> None:
    service = build("calendar", "v3", credentials=credentials)
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
