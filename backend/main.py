import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load .env FIRST before any other imports that might read env vars
_env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=_env_path, override=True)

from fastapi import FastAPI, APIRouter, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from backend.auth import router as auth_router
from backend.calendar_api import build_credentials, list_calendars, fetch_events
from backend.session import get_tokens

app = FastAPI(title="Calendar Chatbot API")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "dev-secret-change-me"),
    same_site="lax",
    https_only=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:5173")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)

api_router = APIRouter(prefix="/api")


@api_router.get("/calendars")
def get_calendars(request: Request):
    tokens = get_tokens(request)
    if not tokens:
        raise HTTPException(status_code=401, detail="Not authenticated")
    creds = build_credentials(tokens)
    return list_calendars(creds)


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
    events, next_token = fetch_events(
        creds,
        calendar_id=calendarId,
        q=q,
        time_min=from_date,
        time_max=to_date,
        max_results=maxResults,
        page_token=pageToken,
    )
    return {"events": events, "nextPageToken": next_token}


app.include_router(api_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/debug/env")
def debug_env():
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    return {
        "env_file": str(_env_path),
        "env_file_exists": _env_path.exists(),
        "client_id_loaded": bool(client_id and client_id != "FILL_IN"),
        "client_id_preview": client_id[:30] + "..." if len(client_id) > 30 else client_id,
        "secret_loaded": bool(secret and secret != "FILL_IN"),
    }
