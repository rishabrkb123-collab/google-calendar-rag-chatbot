# Phase 1: Google Calendar UI + Search + Filter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a full-stack web app that authenticates with Google Calendar via OAuth2, fetches and displays all events, and provides live search and multi-dimensional filtering.

**Architecture:** FastAPI backend handles Google OAuth2 and Calendar API calls, storing tokens in a signed server-side session cookie. A React/Vite frontend calls the backend REST API, renders events as animated cards, and provides debounced search + filter controls.

**Tech Stack:** Python 3.11+, FastAPI, google-auth-oauthlib, google-api-python-client, starlette SessionMiddleware, React 18, Vite, TailwindCSS, Framer Motion, Axios, Vitest, pytest

---

## Pre-requisites: Google Cloud Setup

Before writing any code, the user must:

1. Go to https://console.cloud.google.com
2. Create a new project (or select existing)
3. Navigate to **APIs & Services → Library**, search "Google Calendar API", click Enable
4. Navigate to **APIs & Services → OAuth consent screen**
   - Choose **External**, fill in App name, user support email, developer contact email
   - Add scope: `https://www.googleapis.com/auth/calendar.readonly`
   - Add your Google account as a test user
5. Navigate to **APIs & Services → Credentials → Create Credentials → OAuth client ID**
   - Application type: **Web application**
   - Authorized redirect URIs: `http://localhost:8000/auth/callback`
   - Download the JSON — note `client_id` and `client_secret`
6. Create `backend/.env` with:

```
GOOGLE_CLIENT_ID=your_client_id_here
GOOGLE_CLIENT_SECRET=your_client_secret_here
SECRET_KEY=a-long-random-string-change-this
REDIRECT_URI=http://localhost:8000/auth/callback
FRONTEND_URL=http://localhost:5173
```

---

## File Map

```
backend/
  main.py           — FastAPI app, CORS, session middleware, router registration
  auth.py           — OAuth2 routes: /auth/login, /auth/callback, /auth/status, /auth/logout
  calendar_api.py   — Google Calendar API calls: list_calendars(), fetch_events()
  session.py        — Token read/write helpers on top of Starlette session
  requirements.txt
  .env              — Credentials (never committed)

tests/backend/
  conftest.py       — Shared pytest fixtures (test client, mock creds)
  test_auth.py      — Auth route tests
  test_calendar_api.py — Calendar API unit tests

frontend/
  index.html
  package.json
  vite.config.js
  tailwind.config.js
  postcss.config.js
  src/
    main.jsx        — React entry point
    App.jsx         — Router + AuthContext provider + page routes
    api/
      client.js     — Axios instance configured for backend
    context/
      AuthContext.jsx — Auth state (isAuthenticated, user, loading)
    pages/
      LoginPage.jsx  — Animated connect button
      Dashboard.jsx  — Main layout: navbar + search + filters + event list
    components/
      Navbar.jsx     — Top bar: logo, user email, logout
      SearchBar.jsx  — Debounced search input
      FilterPanel.jsx — Date range, calendar selector, quick filters
      EventList.jsx  — Renders list of EventCards with stagger animation
      EventCard.jsx  — Single event: title, time, calendar color, location

start.bat           — Starts backend + frontend, opens browser
```

---

## Task 1: Initialize Project Structure + Python Environment

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/.env` (template only — real values filled by user)
- Create: `backend/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)
- Create: `tests/backend/__init__.py` (empty)

- [ ] **Step 1: Create directory structure**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG"
mkdir -p backend tests/backend
```

- [ ] **Step 2: Create requirements.txt**

Create `backend/requirements.txt`:
```
fastapi==0.111.0
uvicorn[standard]==0.29.0
python-dotenv==1.0.1
google-auth==2.29.0
google-auth-oauthlib==1.2.0
google-api-python-client==2.127.0
starlette==0.37.2
itsdangerous==2.2.0
httpx==0.27.0
pytest==8.2.0
pytest-asyncio==0.23.6
```

- [ ] **Step 3: Create .env template**

Create `backend/.env`:
```
GOOGLE_CLIENT_ID=FILL_IN
GOOGLE_CLIENT_SECRET=FILL_IN
SECRET_KEY=change-this-to-a-long-random-string
REDIRECT_URI=http://localhost:8000/auth/callback
FRONTEND_URL=http://localhost:5173
```

- [ ] **Step 4: Create virtual environment and install dependencies**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG\backend"
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

Expected: packages install without errors.

- [ ] **Step 5: Create empty __init__ files**

```bash
touch backend/__init__.py tests/__init__.py tests/backend/__init__.py
```

- [ ] **Step 6: Commit**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG"
git add backend/requirements.txt backend/.env backend/__init__.py tests/__init__.py tests/backend/__init__.py
git commit -m "chore: initialize backend structure and dependencies"
```

---

## Task 2: Backend — session.py + main.py skeleton

**Files:**
- Create: `backend/session.py`
- Create: `backend/main.py`
- Create: `tests/backend/conftest.py`

- [ ] **Step 1: Write failing test for health endpoint**

Create `tests/backend/conftest.py`:
```python
import pytest
from fastapi.testclient import TestClient
from backend.main import app

@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
```

Create `tests/backend/test_main.py`:
```python
def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG"
backend\venv\Scripts\pytest tests/backend/test_main.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'backend.main'`

- [ ] **Step 3: Create session.py**

Create `backend/session.py`:
```python
from starlette.requests import Request
from typing import Optional

TOKENS_KEY = "google_tokens"
USER_KEY = "google_user"


def save_tokens(request: Request, tokens: dict, user_info: dict) -> None:
    request.session[TOKENS_KEY] = tokens
    request.session[USER_KEY] = user_info


def get_tokens(request: Request) -> Optional[dict]:
    return request.session.get(TOKENS_KEY)


def get_user(request: Request) -> Optional[dict]:
    return request.session.get(USER_KEY)


def clear_session(request: Request) -> None:
    request.session.pop(TOKENS_KEY, None)
    request.session.pop(USER_KEY, None)


def is_authenticated(request: Request) -> bool:
    return get_tokens(request) is not None
```

- [ ] **Step 4: Create main.py**

Create `backend/main.py`:
```python
import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()

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


@app.get("/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG"
backend\venv\Scripts\pytest tests/backend/test_main.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/session.py tests/backend/conftest.py tests/backend/test_main.py
git commit -m "feat: FastAPI skeleton with session middleware and health endpoint"
```

---

## Task 3: Backend — auth.py (OAuth2 routes)

**Files:**
- Create: `backend/auth.py`
- Create: `tests/backend/test_auth.py`
- Modify: `backend/main.py` — register auth router

- [ ] **Step 1: Write failing tests for auth routes**

Create `tests/backend/test_auth.py`:
```python
def test_auth_status_unauthenticated(client):
    response = client.get("/auth/status")
    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    assert response.json()["email"] is None


def test_logout_clears_session(client):
    response = client.post("/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"message": "Logged out"}


def test_login_redirects(client):
    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code in (302, 307)
    location = response.headers.get("location", "")
    assert "accounts.google.com" in location
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
backend\venv\Scripts\pytest tests/backend/test_auth.py -v
```

Expected: FAIL — `404 Not Found` on all auth routes

- [ ] **Step 3: Create auth.py**

Create `backend/auth.py`:
```python
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
```

- [ ] **Step 4: Register router in main.py**

Edit `backend/main.py` — add after the middleware setup:
```python
from backend.auth import router as auth_router
app.include_router(auth_router)
```

Full `backend/main.py` after edit:
```python
import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from backend.auth import router as auth_router

load_dotenv()

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


@app.get("/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 5: Run auth tests**

```bash
backend\venv\Scripts\pytest tests/backend/test_auth.py -v
```

Expected: `test_auth_status_unauthenticated` PASS, `test_logout_clears_session` PASS, `test_login_redirects` PASS (note: login test requires `GOOGLE_CLIENT_ID` set in `.env` — skip with `-k "not login"` if not yet configured)

- [ ] **Step 6: Commit**

```bash
git add backend/auth.py backend/main.py tests/backend/test_auth.py
git commit -m "feat: Google OAuth2 auth routes (login, callback, status, logout)"
```

---

## Task 4: Backend — calendar_api.py + /api/events + /api/calendars

**Files:**
- Create: `backend/calendar_api.py`
- Create: `tests/backend/test_calendar_api.py`
- Modify: `backend/main.py` — register api router

- [ ] **Step 1: Write failing tests**

Create `tests/backend/test_calendar_api.py`:
```python
from unittest.mock import patch, MagicMock
from backend.calendar_api import build_credentials, fetch_events, list_calendars


def test_fetch_events_returns_list():
    mock_creds = MagicMock()
    mock_service = MagicMock()
    mock_events_result = {
        "items": [
            {
                "id": "abc123",
                "summary": "Team standup",
                "start": {"dateTime": "2026-04-14T09:00:00Z"},
                "end": {"dateTime": "2026-04-14T09:30:00Z"},
                "description": "Daily sync",
                "location": "Zoom",
                "organizer": {"email": "boss@example.com"},
                "htmlLink": "https://calendar.google.com/event?id=abc123",
                "colorId": None,
            }
        ],
        "nextPageToken": None,
    }
    mock_service.events.return_value.list.return_value.execute.return_value = mock_events_result

    with patch("backend.calendar_api.build", return_value=mock_service):
        events, next_token = fetch_events(mock_creds, calendar_id="primary")

    assert len(events) == 1
    assert events[0]["id"] == "abc123"
    assert events[0]["title"] == "Team standup"
    assert next_token is None


def test_list_calendars_returns_list():
    mock_creds = MagicMock()
    mock_service = MagicMock()
    mock_cal_result = {
        "items": [
            {"id": "primary", "summary": "My Calendar", "backgroundColor": "#4285F4"}
        ]
    }
    mock_service.calendarList.return_value.list.return_value.execute.return_value = mock_cal_result

    with patch("backend.calendar_api.build", return_value=mock_service):
        calendars = list_calendars(mock_creds)

    assert len(calendars) == 1
    assert calendars[0]["id"] == "primary"
    assert calendars[0]["name"] == "My Calendar"
    assert calendars[0]["color"] == "#4285F4"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
backend\venv\Scripts\pytest tests/backend/test_calendar_api.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'backend.calendar_api'`

- [ ] **Step 3: Create calendar_api.py**

Create `backend/calendar_api.py`:
```python
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
```

- [ ] **Step 4: Create api router and register it**

Add to `backend/main.py` — insert before the health endpoint:
```python
from fastapi import Request as FastAPIRequest
from fastapi import HTTPException
from backend.calendar_api import build_credentials, list_calendars, fetch_events
from backend.session import get_tokens, is_authenticated
from typing import Optional

api_router = APIRouter(prefix="/api")

@api_router.get("/calendars")
def get_calendars(request: FastAPIRequest):
    tokens = get_tokens(request)
    if not tokens:
        raise HTTPException(status_code=401, detail="Not authenticated")
    creds = build_credentials(tokens)
    return list_calendars(creds)


@api_router.get("/events")
def get_events(
    request: FastAPIRequest,
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
```

Full updated `backend/main.py`:
```python
import os
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from backend.auth import router as auth_router
from backend.calendar_api import build_credentials, list_calendars, fetch_events
from backend.session import get_tokens

load_dotenv()

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
```

- [ ] **Step 5: Run all backend tests**

```bash
backend\venv\Scripts\pytest tests/ -v
```

Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/calendar_api.py backend/main.py tests/backend/test_calendar_api.py
git commit -m "feat: calendar API module and /api/events + /api/calendars endpoints"
```

---

## Task 5: Frontend — Vite + React + Tailwind scaffold

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.js`
- Create: `frontend/tailwind.config.js`
- Create: `frontend/postcss.config.js`
- Create: `frontend/index.html`
- Create: `frontend/src/main.jsx`
- Create: `frontend/src/App.jsx`
- Create: `frontend/src/index.css`

- [ ] **Step 1: Scaffold with Vite**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG"
npm create vite@latest frontend -- --template react
cd frontend
npm install
npm install -D tailwindcss@3 postcss autoprefixer
npx tailwindcss init -p
npm install axios framer-motion react-router-dom react-datepicker date-fns
npm install -D vitest @vitest/ui @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom
```

- [ ] **Step 2: Configure tailwind.config.js**

Replace `frontend/tailwind.config.js` with:
```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
}
```

- [ ] **Step 3: Configure vite.config.js**

Replace `frontend/vite.config.js` with:
```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/auth': 'http://localhost:8000',
      '/api': 'http://localhost:8000',
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test-setup.js',
  },
})
```

- [ ] **Step 4: Create test setup file**

Create `frontend/src/test-setup.js`:
```js
import '@testing-library/jest-dom'
```

- [ ] **Step 5: Add Tailwind directives to index.css**

Replace `frontend/src/index.css` with:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

body {
  @apply bg-gray-950 text-gray-100 antialiased;
}
```

- [ ] **Step 6: Add vitest script to package.json**

Edit `frontend/package.json` — add to `"scripts"`:
```json
"test": "vitest",
"test:ui": "vitest --ui"
```

- [ ] **Step 7: Write a smoke test**

Create `frontend/src/App.test.jsx`:
```jsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'

describe('App smoke test', () => {
  it('renders without crashing', () => {
    const { container } = render(<div>Calendar App</div>)
    expect(container).toBeTruthy()
  })
})
```

- [ ] **Step 8: Run test**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG\frontend"
npm test -- --run
```

Expected: PASS

- [ ] **Step 9: Commit**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG"
git add frontend/
git commit -m "chore: scaffold React/Vite frontend with Tailwind, Framer Motion, Vitest"
```

---

## Task 6: Frontend — Axios client + AuthContext

**Files:**
- Create: `frontend/src/api/client.js`
- Create: `frontend/src/context/AuthContext.jsx`
- Create: `frontend/src/context/AuthContext.test.jsx`

- [ ] **Step 1: Write failing test for AuthContext**

Create `frontend/src/context/AuthContext.test.jsx`:
```jsx
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { AuthProvider, useAuth } from './AuthContext'
import api from '../api/client'

vi.mock('../api/client')

function TestConsumer() {
  const { isAuthenticated, user, loading } = useAuth()
  if (loading) return <div>Loading</div>
  return (
    <div>
      <span data-testid="auth">{isAuthenticated ? 'yes' : 'no'}</span>
      <span data-testid="email">{user?.email ?? 'none'}</span>
    </div>
  )
}

describe('AuthContext', () => {
  it('shows unauthenticated when API returns false', async () => {
    api.get = vi.fn().mockResolvedValue({ data: { authenticated: false, email: null } })
    render(<AuthProvider><TestConsumer /></AuthProvider>)
    await waitFor(() => expect(screen.getByTestId('auth').textContent).toBe('no'))
    expect(screen.getByTestId('email').textContent).toBe('none')
  })

  it('shows authenticated with email when API returns true', async () => {
    api.get = vi.fn().mockResolvedValue({ data: { authenticated: true, email: 'user@example.com' } })
    render(<AuthProvider><TestConsumer /></AuthProvider>)
    await waitFor(() => expect(screen.getByTestId('auth').textContent).toBe('yes'))
    expect(screen.getByTestId('email').textContent).toBe('user@example.com')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npm test -- --run src/context/AuthContext.test.jsx
```

Expected: FAIL — module not found

- [ ] **Step 3: Create api/client.js**

Create `frontend/src/api/client.js`:
```js
import axios from 'axios'

const api = axios.create({
  baseURL: '',
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      window.location.href = '/'
    }
    return Promise.reject(error)
  }
)

export default api
```

- [ ] **Step 4: Create AuthContext.jsx**

Create `frontend/src/context/AuthContext.jsx`:
```jsx
import { createContext, useContext, useEffect, useState } from 'react'
import api from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/auth/status')
      .then(({ data }) => {
        setIsAuthenticated(data.authenticated)
        setUser(data.authenticated ? { email: data.email } : null)
      })
      .catch(() => setIsAuthenticated(false))
      .finally(() => setLoading(false))
  }, [])

  const logout = async () => {
    await api.post('/auth/logout')
    setIsAuthenticated(false)
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ isAuthenticated, user, loading, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
```

- [ ] **Step 5: Run test to verify it passes**

```bash
npm test -- --run src/context/AuthContext.test.jsx
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG"
git add frontend/src/api/ frontend/src/context/
git commit -m "feat: Axios client and AuthContext with /auth/status polling"
```

---

## Task 7: Frontend — App.jsx routing + main.jsx

**Files:**
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/main.jsx`

- [ ] **Step 1: Update main.jsx**

Replace `frontend/src/main.jsx`:
```jsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
)
```

- [ ] **Step 2: Update App.jsx**

Replace `frontend/src/App.jsx`:
```jsx
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import LoginPage from './pages/LoginPage'
import Dashboard from './pages/Dashboard'

function ProtectedRoute({ children }) {
  const { isAuthenticated, loading } = useAuth()
  if (loading) return (
    <div className="flex items-center justify-center h-screen">
      <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
    </div>
  )
  return isAuthenticated ? children : <Navigate to="/" replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LoginPage />} />
      <Route path="/dashboard" element={
        <ProtectedRoute><Dashboard /></ProtectedRoute>
      } />
    </Routes>
  )
}
```

- [ ] **Step 3: Create placeholder pages (to be replaced in later tasks)**

Create `frontend/src/pages/LoginPage.jsx`:
```jsx
export default function LoginPage() {
  return <div className="flex items-center justify-center h-screen">Login</div>
}
```

Create `frontend/src/pages/Dashboard.jsx`:
```jsx
export default function Dashboard() {
  return <div className="p-8">Dashboard</div>
}
```

- [ ] **Step 4: Verify dev server starts**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG\frontend"
npm run dev
```

Expected: Server starts at http://localhost:5173 without errors. Ctrl+C to stop.

- [ ] **Step 5: Commit**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG"
git add frontend/src/App.jsx frontend/src/main.jsx frontend/src/pages/
git commit -m "feat: React Router setup with auth-guarded routes"
```

---

## Task 8: Frontend — LoginPage

**Files:**
- Modify: `frontend/src/pages/LoginPage.jsx`
- Create: `frontend/src/pages/LoginPage.test.jsx`

- [ ] **Step 1: Write failing test**

Create `frontend/src/pages/LoginPage.test.jsx`:
```jsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { AuthContext } from '../context/AuthContext'
import LoginPage from './LoginPage'

const renderLogin = () =>
  render(
    <AuthContext.Provider value={{ isAuthenticated: false, loading: false }}>
      <MemoryRouter><LoginPage /></MemoryRouter>
    </AuthContext.Provider>
  )

describe('LoginPage', () => {
  it('renders connect button', () => {
    renderLogin()
    expect(screen.getByRole('button', { name: /connect google calendar/i })).toBeInTheDocument()
  })

  it('navigates to /auth/login on button click', () => {
    const originalLocation = window.location
    delete window.location
    window.location = { href: '' }
    renderLogin()
    fireEvent.click(screen.getByRole('button', { name: /connect google calendar/i }))
    expect(window.location.href).toBe('/auth/login')
    window.location = originalLocation
  })
})
```

Export `AuthContext` from `AuthContext.jsx` — add this line to `frontend/src/context/AuthContext.jsx`:
```jsx
export { AuthContext }
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npm test -- --run src/pages/LoginPage.test.jsx
```

Expected: FAIL

- [ ] **Step 3: Implement LoginPage.jsx**

Replace `frontend/src/pages/LoginPage.jsx`:
```jsx
import { motion } from 'framer-motion'

export default function LoginPage() {
  const handleConnect = () => {
    window.location.href = '/auth/login'
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
        className="bg-gray-900 border border-gray-800 rounded-2xl p-10 w-full max-w-md text-center shadow-2xl"
      >
        <div className="flex justify-center mb-6">
          <div className="w-16 h-16 bg-blue-600 rounded-2xl flex items-center justify-center shadow-lg">
            <svg className="w-9 h-9 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
          </div>
        </div>

        <h1 className="text-2xl font-bold text-white mb-2">Calendar Assistant</h1>
        <p className="text-gray-400 mb-8 text-sm leading-relaxed">
          Connect your Google Calendar to search, filter, and explore your events with AI-powered insights.
        </p>

        <motion.button
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
          onClick={handleConnect}
          className="w-full flex items-center justify-center gap-3 bg-white text-gray-900 font-semibold py-3 px-6 rounded-xl hover:bg-gray-100 transition-colors shadow-md"
        >
          <svg className="w-5 h-5" viewBox="0 0 24 24">
            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
          </svg>
          Connect Google Calendar
        </motion.button>

        <p className="text-gray-600 text-xs mt-6">
          Read-only access · Your data stays on your machine
        </p>
      </motion.div>
    </div>
  )
}
```

- [ ] **Step 4: Run test**

```bash
npm test -- --run src/pages/LoginPage.test.jsx
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG"
git add frontend/src/pages/LoginPage.jsx frontend/src/pages/LoginPage.test.jsx frontend/src/context/AuthContext.jsx
git commit -m "feat: LoginPage with Google OAuth connect button and animations"
```

---

## Task 9: Frontend — EventCard component

**Files:**
- Create: `frontend/src/components/EventCard.jsx`
- Create: `frontend/src/components/EventCard.test.jsx`

- [ ] **Step 1: Write failing test**

Create `frontend/src/components/EventCard.test.jsx`:
```jsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import EventCard from './EventCard'

const mockEvent = {
  id: '1',
  title: 'Team Standup',
  start: { dateTime: '2026-04-14T09:00:00Z' },
  end: { dateTime: '2026-04-14T09:30:00Z' },
  description: 'Daily sync meeting',
  location: 'Zoom',
  allDay: false,
  colorId: null,
}

const mockCalendars = [{ id: 'primary', name: 'My Calendar', color: '#4285F4' }]

describe('EventCard', () => {
  it('renders event title', () => {
    render(<EventCard event={mockEvent} calendarColor="#4285F4" />)
    expect(screen.getByText('Team Standup')).toBeInTheDocument()
  })

  it('renders location when present', () => {
    render(<EventCard event={mockEvent} calendarColor="#4285F4" />)
    expect(screen.getByText('Zoom')).toBeInTheDocument()
  })

  it('does not render location when absent', () => {
    const noLocation = { ...mockEvent, location: '' }
    render(<EventCard event={noLocation} calendarColor="#4285F4" />)
    expect(screen.queryByText('Zoom')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npm test -- --run src/components/EventCard.test.jsx
```

Expected: FAIL

- [ ] **Step 3: Implement EventCard.jsx**

Create `frontend/src/components/EventCard.jsx`:
```jsx
import { motion } from 'framer-motion'
import { format, parseISO } from 'date-fns'

function formatEventTime(event) {
  if (event.allDay) {
    const date = event.start.date
    return format(parseISO(date), 'MMM d, yyyy') + ' · All day'
  }
  const start = parseISO(event.start.dateTime)
  const end = parseISO(event.end.dateTime)
  return `${format(start, 'MMM d, yyyy')} · ${format(start, 'h:mm a')} – ${format(end, 'h:mm a')}`
}

export default function EventCard({ event, calendarColor = '#4285F4', index = 0 }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: index * 0.03 }}
      className="bg-gray-900 border border-gray-800 rounded-xl p-4 hover:border-gray-600 transition-colors group"
    >
      <div className="flex items-start gap-3">
        <div
          className="w-1 rounded-full flex-shrink-0 mt-1 self-stretch min-h-[2rem]"
          style={{ backgroundColor: calendarColor }}
        />
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-white text-sm leading-snug truncate group-hover:text-blue-300 transition-colors">
            {event.title}
          </h3>
          <p className="text-gray-400 text-xs mt-1">
            {formatEventTime(event)}
          </p>
          {event.location && (
            <div className="flex items-center gap-1 mt-1.5">
              <svg className="w-3 h-3 text-gray-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
              <span className="text-gray-500 text-xs truncate">{event.location}</span>
            </div>
          )}
          {event.description && (
            <p className="text-gray-600 text-xs mt-1.5 line-clamp-2">{event.description}</p>
          )}
        </div>
      </div>
    </motion.div>
  )
}
```

- [ ] **Step 4: Run test**

```bash
npm test -- --run src/components/EventCard.test.jsx
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG"
git add frontend/src/components/EventCard.jsx frontend/src/components/EventCard.test.jsx
git commit -m "feat: EventCard component with animated entrance and event details"
```

---

## Task 10: Frontend — SearchBar component

**Files:**
- Create: `frontend/src/components/SearchBar.jsx`
- Create: `frontend/src/components/SearchBar.test.jsx`

- [ ] **Step 1: Write failing test**

Create `frontend/src/components/SearchBar.test.jsx`:
```jsx
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import SearchBar from './SearchBar'

describe('SearchBar', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('renders search input', () => {
    render(<SearchBar value="" onChange={() => {}} />)
    expect(screen.getByPlaceholderText(/search events/i)).toBeInTheDocument()
  })

  it('calls onChange after debounce delay', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<SearchBar value="" onChange={onChange} debounceMs={300} />)
    await user.type(screen.getByPlaceholderText(/search events/i), 'standup')
    expect(onChange).not.toHaveBeenCalled()
    act(() => { vi.advanceTimersByTime(300) })
    expect(onChange).toHaveBeenCalledWith('standup')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
npm test -- --run src/components/SearchBar.test.jsx
```

Expected: FAIL

- [ ] **Step 3: Implement SearchBar.jsx**

Create `frontend/src/components/SearchBar.jsx`:
```jsx
import { useState, useEffect, useRef } from 'react'

export default function SearchBar({ value, onChange, debounceMs = 300 }) {
  const [localValue, setLocalValue] = useState(value)
  const timerRef = useRef(null)

  useEffect(() => {
    setLocalValue(value)
  }, [value])

  const handleChange = (e) => {
    const val = e.target.value
    setLocalValue(val)
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => onChange(val), debounceMs)
  }

  const handleClear = () => {
    setLocalValue('')
    clearTimeout(timerRef.current)
    onChange('')
  }

  return (
    <div className="relative w-full">
      <div className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500">
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
      </div>
      <input
        type="text"
        value={localValue}
        onChange={handleChange}
        placeholder="Search events..."
        className="w-full bg-gray-900 border border-gray-700 rounded-xl pl-10 pr-10 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 transition-colors"
      />
      {localValue && (
        <button
          onClick={handleClear}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run test**

```bash
npm test -- --run src/components/SearchBar.test.jsx
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG"
git add frontend/src/components/SearchBar.jsx frontend/src/components/SearchBar.test.jsx
git commit -m "feat: debounced SearchBar component"
```

---

## Task 11: Frontend — FilterPanel component

**Files:**
- Create: `frontend/src/components/FilterPanel.jsx`
- Create: `frontend/src/components/FilterPanel.test.jsx`

- [ ] **Step 1: Write failing test**

Create `frontend/src/components/FilterPanel.test.jsx`:
```jsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import FilterPanel from './FilterPanel'

const mockCalendars = [
  { id: 'primary', name: 'My Calendar', color: '#4285F4' },
  { id: 'work', name: 'Work', color: '#0F9D58' },
]

const defaultFilters = { calendarIds: ['primary', 'work'], fromDate: '', toDate: '', quickFilter: '' }

describe('FilterPanel', () => {
  it('renders all calendars as checkboxes', () => {
    render(
      <FilterPanel
        calendars={mockCalendars}
        filters={defaultFilters}
        onChange={() => {}}
      />
    )
    expect(screen.getByLabelText('My Calendar')).toBeInTheDocument()
    expect(screen.getByLabelText('Work')).toBeInTheDocument()
  })

  it('calls onChange when quick filter is clicked', () => {
    const onChange = vi.fn()
    render(
      <FilterPanel
        calendars={mockCalendars}
        filters={defaultFilters}
        onChange={onChange}
      />
    )
    fireEvent.click(screen.getByText('Today'))
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ quickFilter: 'today' }))
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
npm test -- --run src/components/FilterPanel.test.jsx
```

Expected: FAIL

- [ ] **Step 3: Implement FilterPanel.jsx**

Create `frontend/src/components/FilterPanel.jsx`:
```jsx
import { motion } from 'framer-motion'

const QUICK_FILTERS = [
  { label: 'Today', value: 'today' },
  { label: 'This Week', value: 'week' },
  { label: 'This Month', value: 'month' },
  { label: 'Upcoming', value: 'upcoming' },
]

export default function FilterPanel({ calendars, filters, onChange }) {
  const toggleCalendar = (calId) => {
    const current = filters.calendarIds ?? []
    const updated = current.includes(calId)
      ? current.filter((id) => id !== calId)
      : [...current, calId]
    onChange({ ...filters, calendarIds: updated })
  }

  const setQuickFilter = (value) => {
    onChange({ ...filters, quickFilter: filters.quickFilter === value ? '' : value })
  }

  const setDate = (key, val) => {
    onChange({ ...filters, [key]: val })
  }

  return (
    <motion.aside
      initial={{ x: -20, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      transition={{ duration: 0.3 }}
      className="w-64 flex-shrink-0 space-y-6"
    >
      <div>
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Quick Filters</h3>
        <div className="flex flex-wrap gap-2">
          {QUICK_FILTERS.map(({ label, value }) => (
            <button
              key={value}
              onClick={() => setQuickFilter(value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                filters.quickFilter === value
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div>
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Date Range</h3>
        <div className="space-y-2">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">From</label>
            <input
              type="date"
              value={filters.fromDate}
              onChange={(e) => setDate('fromDate', e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500 [color-scheme:dark]"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">To</label>
            <input
              type="date"
              value={filters.toDate}
              onChange={(e) => setDate('toDate', e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500 [color-scheme:dark]"
            />
          </div>
        </div>
      </div>

      <div>
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Calendars</h3>
        <div className="space-y-2">
          {calendars.map((cal) => (
            <label key={cal.id} className="flex items-center gap-2.5 cursor-pointer group">
              <input
                type="checkbox"
                checked={(filters.calendarIds ?? []).includes(cal.id)}
                onChange={() => toggleCalendar(cal.id)}
                className="sr-only"
                aria-label={cal.name}
                id={`cal-${cal.id}`}
              />
              <label htmlFor={`cal-${cal.id}`} className="sr-only">{cal.name}</label>
              <div
                onClick={() => toggleCalendar(cal.id)}
                className={`w-4 h-4 rounded flex items-center justify-center border-2 flex-shrink-0 cursor-pointer transition-colors`}
                style={{
                  backgroundColor: (filters.calendarIds ?? []).includes(cal.id) ? cal.color : 'transparent',
                  borderColor: cal.color,
                }}
              >
                {(filters.calendarIds ?? []).includes(cal.id) && (
                  <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                  </svg>
                )}
              </div>
              <span
                onClick={() => toggleCalendar(cal.id)}
                className="text-xs text-gray-300 group-hover:text-white transition-colors cursor-pointer truncate"
              >
                {cal.name}
              </span>
            </label>
          ))}
        </div>
      </div>
    </motion.aside>
  )
}
```

- [ ] **Step 4: Run test**

```bash
npm test -- --run src/components/FilterPanel.test.jsx
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG"
git add frontend/src/components/FilterPanel.jsx frontend/src/components/FilterPanel.test.jsx
git commit -m "feat: FilterPanel with quick filters, date range, and calendar checkboxes"
```

---

## Task 12: Frontend — EventList component

**Files:**
- Create: `frontend/src/components/EventList.jsx`
- Create: `frontend/src/components/EventList.test.jsx`

- [ ] **Step 1: Write failing test**

Create `frontend/src/components/EventList.test.jsx`:
```jsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import EventList from './EventList'

const mockEvents = [
  {
    id: '1',
    title: 'Standup',
    start: { dateTime: '2026-04-14T09:00:00Z' },
    end: { dateTime: '2026-04-14T09:30:00Z' },
    description: '',
    location: '',
    allDay: false,
    colorId: null,
  },
  {
    id: '2',
    title: 'Lunch',
    start: { dateTime: '2026-04-14T12:00:00Z' },
    end: { dateTime: '2026-04-14T13:00:00Z' },
    description: '',
    location: 'Cafeteria',
    allDay: false,
    colorId: null,
  },
]

describe('EventList', () => {
  it('renders all events', () => {
    render(<EventList events={mockEvents} calendars={[]} loading={false} />)
    expect(screen.getByText('Standup')).toBeInTheDocument()
    expect(screen.getByText('Lunch')).toBeInTheDocument()
  })

  it('shows loading state', () => {
    render(<EventList events={[]} calendars={[]} loading={true} />)
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
  })

  it('shows empty state when no events', () => {
    render(<EventList events={[]} calendars={[]} loading={false} />)
    expect(screen.getByText(/no events found/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
npm test -- --run src/components/EventList.test.jsx
```

Expected: FAIL

- [ ] **Step 3: Implement EventList.jsx**

Create `frontend/src/components/EventList.jsx`:
```jsx
import { motion, AnimatePresence } from 'framer-motion'
import EventCard from './EventCard'

function getCalendarColor(event, calendars) {
  const cal = calendars.find((c) => c.id === event.calendarId)
  return cal?.color ?? '#4285F4'
}

export default function EventList({ events, calendars, loading }) {
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-gray-500">
        <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mb-4" />
        <p className="text-sm">Loading events...</p>
      </div>
    )
  }

  if (!events.length) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-gray-600">
        <svg className="w-16 h-16 mb-4 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1}
            d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
        <p className="text-sm font-medium">No events found</p>
        <p className="text-xs mt-1 text-gray-700">Try adjusting your search or filters</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-gray-600 mb-3">{events.length} event{events.length !== 1 ? 's' : ''}</p>
      <AnimatePresence>
        {events.map((event, index) => (
          <EventCard
            key={event.id}
            event={event}
            calendarColor={getCalendarColor(event, calendars)}
            index={index}
          />
        ))}
      </AnimatePresence>
    </div>
  )
}
```

- [ ] **Step 4: Run test**

```bash
npm test -- --run src/components/EventList.test.jsx
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG"
git add frontend/src/components/EventList.jsx frontend/src/components/EventList.test.jsx
git commit -m "feat: EventList with loading and empty states"
```

---

## Task 13: Frontend — Navbar component

**Files:**
- Create: `frontend/src/components/Navbar.jsx`

- [ ] **Step 1: Create Navbar.jsx**

Create `frontend/src/components/Navbar.jsx`:
```jsx
import { useAuth } from '../context/AuthContext'

export default function Navbar() {
  const { user, logout } = useAuth()

  return (
    <header className="sticky top-0 z-10 bg-gray-950/90 backdrop-blur border-b border-gray-800 px-6 py-4">
      <div className="max-w-7xl mx-auto flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 bg-blue-600 rounded-lg flex items-center justify-center">
            <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
          </div>
          <span className="font-semibold text-white text-sm">Calendar Assistant</span>
        </div>

        <div className="flex items-center gap-4">
          {user?.email && (
            <span className="text-gray-400 text-sm hidden sm:block">{user.email}</span>
          )}
          <button
            onClick={logout}
            className="text-xs text-gray-500 hover:text-white transition-colors px-3 py-1.5 rounded-lg hover:bg-gray-800"
          >
            Sign out
          </button>
        </div>
      </div>
    </header>
  )
}
```

- [ ] **Step 2: Commit**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG"
git add frontend/src/components/Navbar.jsx
git commit -m "feat: Navbar with user email and logout"
```

---

## Task 14: Frontend — Dashboard page (wire everything together)

**Files:**
- Modify: `frontend/src/pages/Dashboard.jsx`
- Create: `frontend/src/pages/Dashboard.test.jsx`

- [ ] **Step 1: Write failing test**

Create `frontend/src/pages/Dashboard.test.jsx`:
```jsx
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { AuthContext } from '../context/AuthContext'
import Dashboard from './Dashboard'
import api from '../api/client'

vi.mock('../api/client')

const authValue = { isAuthenticated: true, user: { email: 'test@example.com' }, loading: false, logout: vi.fn() }

describe('Dashboard', () => {
  it('shows loading spinner initially', () => {
    api.get = vi.fn().mockReturnValue(new Promise(() => {}))
    render(
      <AuthContext.Provider value={authValue}>
        <MemoryRouter><Dashboard /></MemoryRouter>
      </AuthContext.Provider>
    )
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
  })

  it('renders events after loading', async () => {
    api.get = vi.fn().mockImplementation((url) => {
      if (url === '/api/calendars') return Promise.resolve({ data: [{ id: 'primary', name: 'My Cal', color: '#4285F4' }] })
      if (url.startsWith('/api/events')) return Promise.resolve({ data: { events: [
        { id: '1', title: 'Test Event', start: { dateTime: '2026-04-14T09:00:00Z' }, end: { dateTime: '2026-04-14T10:00:00Z' }, description: '', location: '', allDay: false }
      ], nextPageToken: null } })
      return Promise.resolve({ data: {} })
    })
    render(
      <AuthContext.Provider value={authValue}>
        <MemoryRouter><Dashboard /></MemoryRouter>
      </AuthContext.Provider>
    )
    await waitFor(() => expect(screen.getByText('Test Event')).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npm test -- --run src/pages/Dashboard.test.jsx
```

Expected: FAIL

- [ ] **Step 3: Implement Dashboard.jsx**

Replace `frontend/src/pages/Dashboard.jsx`:
```jsx
import { useState, useEffect, useCallback } from 'react'
import { startOfDay, endOfDay, startOfWeek, endOfWeek, startOfMonth, endOfMonth, addMonths, formatISO } from 'date-fns'
import api from '../api/client'
import Navbar from '../components/Navbar'
import SearchBar from '../components/SearchBar'
import FilterPanel from '../components/FilterPanel'
import EventList from '../components/EventList'

function quickFilterToDates(quickFilter) {
  const now = new Date()
  switch (quickFilter) {
    case 'today':
      return { from: formatISO(startOfDay(now)), to: formatISO(endOfDay(now)) }
    case 'week':
      return { from: formatISO(startOfWeek(now)), to: formatISO(endOfWeek(now)) }
    case 'month':
      return { from: formatISO(startOfMonth(now)), to: formatISO(endOfMonth(now)) }
    case 'upcoming':
      return { from: formatISO(now), to: formatISO(addMonths(now, 3)) }
    default:
      return { from: null, to: null }
  }
}

export default function Dashboard() {
  const [events, setEvents] = useState([])
  const [calendars, setCalendars] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState({
    calendarIds: [],
    fromDate: '',
    toDate: '',
    quickFilter: 'upcoming',
  })

  useEffect(() => {
    api.get('/api/calendars').then(({ data }) => {
      setCalendars(data)
      setFilters((f) => ({ ...f, calendarIds: data.map((c) => c.id) }))
    })
  }, [])

  const fetchEvents = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (search) params.set('q', search)
      if (filters.calendarIds.length === 1) params.set('calendarId', filters.calendarIds[0])

      const dates = filters.quickFilter
        ? quickFilterToDates(filters.quickFilter)
        : { from: filters.fromDate || null, to: filters.toDate || null }

      if (dates.from) params.set('from_date', dates.from)
      if (dates.to) params.set('to_date', dates.to)
      params.set('maxResults', '250')

      const { data } = await api.get(`/api/events?${params.toString()}`)
      setEvents(data.events ?? [])
    } finally {
      setLoading(false)
    }
  }, [search, filters])

  useEffect(() => {
    fetchEvents()
  }, [fetchEvents])

  return (
    <div className="min-h-screen bg-gray-950">
      <Navbar />
      <div className="max-w-7xl mx-auto px-6 py-6">
        <div className="mb-6">
          <SearchBar value={search} onChange={setSearch} />
        </div>
        <div className="flex gap-8">
          <FilterPanel calendars={calendars} filters={filters} onChange={setFilters} />
          <main className="flex-1 min-w-0">
            <EventList events={events} calendars={calendars} loading={loading} />
          </main>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run test**

```bash
npm test -- --run src/pages/Dashboard.test.jsx
```

Expected: PASS

- [ ] **Step 5: Run all frontend tests**

```bash
npm test -- --run
```

Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG"
git add frontend/src/pages/Dashboard.jsx frontend/src/pages/Dashboard.test.jsx
git commit -m "feat: Dashboard page wiring search, filters, and event list together"
```

---

## Task 15: start.bat — launch everything + open browser

**Files:**
- Create: `start.bat`

- [ ] **Step 1: Create start.bat**

Create `start.bat` in the project root:
```bat
@echo off
setlocal

set ROOT=%~dp0
set BACKEND=%ROOT%backend
set FRONTEND=%ROOT%frontend

echo Starting Calendar Assistant...
echo.

REM Start backend in a new persistent terminal window
start "Calendar Backend" cmd /k "cd /d "%BACKEND%" && venv\Scripts\activate && uvicorn main:app --reload --host 0.0.0.0 --port 8000"

REM Wait for backend to be ready
echo Waiting for backend to start...
timeout /t 4 /nobreak >nul

REM Start frontend in a new persistent terminal window
start "Calendar Frontend" cmd /k "cd /d "%FRONTEND%" && npm run dev"

REM Wait for frontend to be ready
echo Waiting for frontend to start...
timeout /t 5 /nobreak >nul

REM Open browser
echo Opening browser...
start http://localhost:5173

echo.
echo Both servers are running.
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5173
echo.
echo Close the two terminal windows to stop the servers.
endlocal
```

- [ ] **Step 2: Test the batch file**

Double-click `start.bat` or run from terminal:
```bash
cd "D:\Agentic Chatbot Google Calender - RAG"
start.bat
```

Expected:
- Two new terminal windows open (one for backend, one for frontend)
- Browser opens to `http://localhost:5173`
- Login page is visible with the "Connect Google Calendar" button
- No windows flash and close

- [ ] **Step 3: Commit**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG"
git add start.bat
git commit -m "chore: start.bat launches backend + frontend and opens browser"
```

---

## Task 16: Final integration smoke test

- [ ] **Step 1: Run all backend tests**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG"
backend\venv\Scripts\pytest tests/ -v
```

Expected: All PASS

- [ ] **Step 2: Run all frontend tests**

```bash
cd frontend && npm test -- --run
```

Expected: All PASS

- [ ] **Step 3: Start via start.bat and do manual OAuth flow**

1. Run `start.bat`
2. Browser opens to `http://localhost:5173`
3. Click "Connect Google Calendar"
4. Google OAuth consent screen appears
5. Approve → redirected to `/dashboard`
6. Events load with stagger animation
7. Type in search bar → events filter live after 300ms
8. Click "Today" quick filter → events narrow to today
9. Toggle a calendar checkbox → events update
10. Set a date range → events filter by range
11. Click "Sign out" → returns to login page

- [ ] **Step 4: Final commit**

```bash
cd "D:\Agentic Chatbot Google Calender - RAG"
git add .
git commit -m "feat: Phase 1 complete — Google Calendar UI with search and filter"
```
