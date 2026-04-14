from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from backend.config import get_frontend_url, get_google_oauth_config
from backend.session import (
    save_tokens,
    get_tokens,
    get_user,
    clear_session,
    is_authenticated,
)

router = APIRouter(prefix="/auth")

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]


def _make_flow() -> Flow:
    oauth_config = get_google_oauth_config()
    if not oauth_config["client_id"] or not oauth_config["client_secret"]:
        raise HTTPException(
            status_code=500, detail="Google OAuth is not configured correctly"
        )

    return Flow.from_client_config(
        {
            "web": {
                "client_id": oauth_config["client_id"],
                "client_secret": oauth_config["client_secret"],
                "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [oauth_config["redirect_uri"]],
            }
        },
        scopes=SCOPES,
        redirect_uri=oauth_config["redirect_uri"],
    )


@router.get("/login")
def login(request: Request):
    flow = _make_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="select_account consent",
    )
    request.session["oauth_state"] = state
    return RedirectResponse(auth_url)


@router.get("/callback")
def callback(request: Request, code: str, state: str):
    flow = _make_flow()
    flow.fetch_token(code=code)
    credentials = flow.credentials
    tokens = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": list(credentials.scopes) if credentials.scopes else [],
    }
    service = build("oauth2", "v2", credentials=credentials)
    user_info = service.userinfo().get().execute()
    save_tokens(
        request,
        tokens,
        {"email": user_info.get("email"), "name": user_info.get("name")},
    )
    frontend_url = get_frontend_url()
    return RedirectResponse(f"{frontend_url}/dashboard")


@router.get("/status")
def status(request: Request):
    if not is_authenticated(request):
        return {"authenticated": False, "email": None}
    user = get_user(request)
    return {"authenticated": True, "email": user.get("email") if user else None}


@router.post("/logout")
def logout(request: Request):
    clear_session(request)
    return {"message": "Logged out"}
