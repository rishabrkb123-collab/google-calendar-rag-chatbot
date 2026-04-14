from typing import Optional

from fastapi import FastAPI, APIRouter, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from googleapiclient.errors import HttpError
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware
from backend.config import (
    ENV_PATH,
    get_frontend_url,
    get_google_oauth_config,
    get_secret_key,
)
from backend.auth import router as auth_router
from backend.chatbot import router as chatbot_router
from backend.calendar_api import (
    build_credentials,
    delete_event,
    fetch_all_events,
    fetch_events,
    get_event,
    list_calendars,
    translate_google_api_error,
    update_event,
)
from backend.session import get_tokens

app = FastAPI(title="Calendar Chatbot API")

app.add_middleware(
    SessionMiddleware,
    secret_key=get_secret_key(),
    same_site="lax",
    https_only=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_frontend_url()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(chatbot_router)

api_router = APIRouter(prefix="/api")


class EventMutationRequest(BaseModel):
    body: dict = Field(default_factory=dict)


@api_router.get("/calendars")
def get_calendars(request: Request):
    tokens = get_tokens(request)
    if not tokens:
        raise HTTPException(status_code=401, detail="Not authenticated")
    creds = build_credentials(tokens)
    try:
        return list_calendars(creds)
    except HttpError as exc:
        translate_google_api_error(exc)


@api_router.get("/events")
def get_events(
    request: Request,
    q: Optional[str] = None,
    calendarId: str = "primary",
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    maxResults: int = 250,
    pageToken: Optional[str] = None,
):
    tokens = get_tokens(request)
    if not tokens:
        raise HTTPException(status_code=401, detail="Not authenticated")
    creds = build_credentials(tokens)
    try:
        events, next_token = fetch_events(
            creds,
            calendar_id=calendarId,
            q=q,
            time_min=from_date,
            time_max=to_date,
            max_results=maxResults,
            page_token=pageToken,
        )
    except HttpError as exc:
        translate_google_api_error(exc)
    return {"events": events, "nextPageToken": next_token}


@api_router.get("/events/all")
def get_all_events(
    request: Request,
    q: Optional[str] = None,
    calendarIds: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    maxResults: int = 250,
):
    tokens = get_tokens(request)
    if not tokens:
        raise HTTPException(status_code=401, detail="Not authenticated")

    creds = build_credentials(tokens)
    selected_calendar_ids = [
        calendar_id for calendar_id in (calendarIds or "").split(",") if calendar_id
    ]

    try:
        events, scanned_calendar_ids = fetch_all_events(
            creds,
            calendar_ids=selected_calendar_ids or None,
            q=q,
            time_min=from_date,
            time_max=to_date,
            max_results=maxResults,
        )
    except HttpError as exc:
        translate_google_api_error(exc)

    return {
        "events": events,
        "totalEvents": len(events),
        "calendarsScanned": scanned_calendar_ids,
    }


@api_router.get("/event")
def get_single_event(request: Request, calendarId: str, eventId: str):
    tokens = get_tokens(request)
    if not tokens:
        raise HTTPException(status_code=401, detail="Not authenticated")

    creds = build_credentials(tokens)
    try:
        return get_event(creds, calendar_id=calendarId, event_id=eventId)
    except HttpError as exc:
        translate_google_api_error(exc)


@api_router.patch("/event")
def patch_single_event(
    request: Request,
    payload: EventMutationRequest,
    calendarId: str,
    eventId: str,
):
    tokens = get_tokens(request)
    if not tokens:
        raise HTTPException(status_code=401, detail="Not authenticated")

    creds = build_credentials(tokens)
    try:
        return update_event(
            creds, calendar_id=calendarId, event_id=eventId, body=payload.body
        )
    except HttpError as exc:
        translate_google_api_error(exc)


@api_router.delete("/event")
def remove_single_event(request: Request, calendarId: str, eventId: str):
    tokens = get_tokens(request)
    if not tokens:
        raise HTTPException(status_code=401, detail="Not authenticated")

    creds = build_credentials(tokens)
    try:
        delete_event(creds, calendar_id=calendarId, event_id=eventId)
    except HttpError as exc:
        translate_google_api_error(exc)
    return {"ok": True}


app.include_router(api_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/debug/env")
def debug_env():
    oauth_config = get_google_oauth_config()
    client_id = oauth_config["client_id"]
    secret = oauth_config["client_secret"]
    return {
        "env_file": str(ENV_PATH),
        "env_file_exists": ENV_PATH.exists(),
        "oauth_source": oauth_config["source"],
        "credentials_file": oauth_config["credentials_file"],
        "client_id_loaded": bool(client_id and client_id != "FILL_IN"),
        "client_id_preview": client_id[:30] + "..."
        if len(client_id) > 30
        else client_id,
        "secret_loaded": bool(secret and secret != "FILL_IN"),
        "redirect_uri": oauth_config["redirect_uri"],
    }
