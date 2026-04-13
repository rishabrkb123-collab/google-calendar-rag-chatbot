import os
from typing import Optional, Tuple
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


def build_credentials(tokens: dict) -> Credentials:
    creds = Credentials(
        token=tokens["token"],
        refresh_token=tokens.get("refresh_token"),
        token_uri=tokens.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=tokens.get("client_id", os.getenv("GOOGLE_CLIENT_ID")),
        client_secret=tokens.get("client_secret", os.getenv("GOOGLE_CLIENT_SECRET")),
        scopes=tokens.get("scopes"),
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def list_calendars(credentials: Credentials) -> list:
    service = build("calendar", "v3", credentials=credentials)
    result = service.calendarList().list().execute()
    return [
        {
            "id": cal["id"],
            "name": cal.get("summary", ""),
            "color": cal.get("backgroundColor", "#4285F4"),
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
    events = [
        {
            "id": e.get("id"),
            "title": e.get("summary", "(No title)"),
            "start": e.get("start", {}),
            "end": e.get("end", {}),
            "description": e.get("description", ""),
            "location": e.get("location", ""),
            "organizer": e.get("organizer", {}).get("email", ""),
            "link": e.get("htmlLink", ""),
            "colorId": e.get("colorId"),
            "allDay": "date" in e.get("start", {}),
        }
        for e in result.get("items", [])
    ]
    return events, result.get("nextPageToken")
