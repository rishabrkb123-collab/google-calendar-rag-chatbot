import os
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, JSONResponse
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from backend.session import save_tokens, get_tokens, get_user, clear_session, is_authenticated

router = APIRouter(prefix="/auth")

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]


def _make_flow() -> Flow:
    return Flow.from_client_config(
        {
            "web": {
                "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [os.getenv("REDIRECT_URI", "http://localhost:8000/auth/callback")],
            }
        },
        scopes=SCOPES,
        redirect_uri=os.getenv("REDIRECT_URI", "http://localhost:8000/auth/callback"),
    )


@router.get("/login")
def login(request: Request):
    flow = _make_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
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
    save_tokens(request, tokens, {"email": user_info.get("email"), "name": user_info.get("name")})
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
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
