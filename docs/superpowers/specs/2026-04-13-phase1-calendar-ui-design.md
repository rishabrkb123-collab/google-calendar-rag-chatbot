# Phase 1 Design: Google Calendar UI + Search + Filter

**Date:** 2026-04-13  
**Status:** Approved  
**Scope:** OAuth2 login, calendar event display, search, and filter UI

## Overview

A web app that authenticates with Google Calendar via browser-based OAuth2, fetches all the user's events, and presents them in an animated, interactive dashboard with full-text search and multi-dimensional filtering.

This is Phase 1 of a multi-phase project. The backend is Python (FastAPI) so Phase 2 (RAG + Ollama) can be added without architectural changes.


## Stack

| Layer | Technology | Reason |
|---|---|---|
| Frontend | React 18 + Vite | Fast dev server, modern component model |
| Styling | TailwindCSS | Utility-first, rapid UI development |
| Animation | Framer Motion | Smooth card/page transitions |
| Backend | Python FastAPI | Async, fast, ideal for Phase 2 RAG/Ollama |
| Auth | google-auth-oauthlib | Official Google OAuth2 library |
| Calendar API | google-api-python-client | Official Google Calendar client |
| Session | itsdangerous (server-side) | Secure signed cookies for token storage |
| HTTP client | Axios (frontend) | Clean API calls with interceptors |
| Startup | Windows .bat file | Starts both servers + opens browser |


## Architecture

```
┌─────────────────────────────┐
│   Browser (React/Vite :5173)│
│  ┌──────────┐ ┌───────────┐ │
│  │LoginPage │ │Dashboard  │ │
│  └──────────┘ └───────────┘ │
└────────────┬────────────────┘
             │ REST API (JSON)
┌────────────▼────────────────┐
│   FastAPI Backend (:8000)   │
│  /auth/*   /api/events      │
│  /api/calendars             │
└────────────┬────────────────┘
             │ OAuth2 + API calls
┌────────────▼────────────────┐
│     Google Calendar API     │
└─────────────────────────────┘
```


## Backend

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/auth/login` | Redirect to Google OAuth consent screen |
| `GET` | `/auth/callback` | Receive OAuth code, exchange for tokens, store in session |
| `GET` | `/auth/status` | Return `{ authenticated: bool, email: str }` |
| `POST` | `/auth/logout` | Clear session |
| `GET` | `/api/calendars` | List all user calendars (id, name, color) |
| `GET` | `/api/events` | Fetch events with optional filters (see params below) |

### `/api/events` Query Parameters

| Param | Type | Description |
|---|---|---|
| `q` | string | Full-text search (title, description, location) |
| `calendarId` | string | Filter by specific calendar (default: `primary`) |
| `from` | ISO date | Start of date range |
| `to` | ISO date | End of date range |
| `maxResults` | int | Max events to return (default: 250) |
| `pageToken` | string | Pagination token |

### Session & Token Storage

- Tokens stored in a server-side signed cookie session (itsdangerous)
- On token expiry, auto-refresh using stored refresh token before retrying
- CORS configured to allow only `http://localhost:5173`


## Frontend

### Pages

**LoginPage**
- Centered card with Google Calendar logo
- Animated "Connect Google Calendar" button (Framer Motion pulse/hover)
- On click → calls `/auth/login` → redirects to Google consent

**Dashboard**
- Sticky top bar: app name + user email + logout button
- `SearchBar`: debounced (300ms), searches across title/description/location
- `FilterPanel`: collapsible side panel with:
  - Date range picker (from/to)
  - Calendar selector (multi-select checkboxes, color-coded)
  - Quick filters: Today, This Week, This Month, Upcoming
- `EventList`: paginated grid/list of `EventCard` components
- `EventCard`: shows title, date/time, calendar color dot, location (if any), description snippet

### Animations (Framer Motion)

- Page transition: fade + slide between Login and Dashboard
- EventCard entrance: staggered fade-in as list loads
- FilterPanel: slide in/out from left
- SearchBar: expand on focus

### State Management

- React Context for auth state (authenticated, user email)
- Local component state for search/filter values
- `useEffect` + debounce for API calls on filter/search changes


## Startup (start.bat)

The batch file:
1. Starts FastAPI backend (`uvicorn main:app --reload`) in a new terminal window
2. Waits ~3 seconds for backend to be ready
3. Starts React Vite dev server (`npm run dev`) in a new terminal window
4. Waits ~4 seconds for Vite to be ready
5. Opens `http://localhost:5173` in the default browser

Both processes run in separate persistent terminal windows (not flash-and-close).


## Project Structure

```
D:\Agentic Chatbot Google Calender - RAG\
├── backend\
│   ├── main.py              # FastAPI app, routes
│   ├── auth.py              # Google OAuth2 logic
│   ├── calendar_api.py      # Google Calendar API calls
│   ├── session.py           # Session/cookie management
│   ├── requirements.txt
│   └── .env                 # GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SECRET_KEY
├── frontend\
│   ├── src\
│   │   ├── components\
│   │   │   ├── SearchBar.jsx
│   │   │   ├── FilterPanel.jsx
│   │   │   ├── EventList.jsx
│   │   │   └── EventCard.jsx
│   │   ├── pages\
│   │   │   ├── LoginPage.jsx
│   │   │   └── Dashboard.jsx
│   │   ├── context\
│   │   │   └── AuthContext.jsx
│   │   ├── api\
│   │   │   └── client.js    # Axios instance
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── index.html
│   ├── package.json
│   ├── tailwind.config.js
│   └── vite.config.js
├── docs\
│   └── superpowers\
│       └── specs\
│           └── 2026-04-13-phase1-calendar-ui-design.md
├── start.bat
└── CLAUDE.md
```


## Data Flow

### First-time login
```
User clicks "Connect" 
  → GET /auth/login 
  → Redirect to Google consent 
  → User approves 
  → Google redirects to /auth/callback?code=...
  → Backend exchanges code for tokens
  → Tokens stored in signed session cookie
  → Backend redirects to frontend /dashboard
  → Frontend calls /auth/status → authenticated: true
  → Dashboard loads
```

### Fetching events
```
Dashboard mounts / filter changes
  → Frontend calls GET /api/events?q=...&from=...&to=...
  → Backend checks session for tokens
  → Backend calls Google Calendar API
  → Returns events as JSON array
  → Frontend renders EventCards with stagger animation
```


## Error Handling

- If `/auth/status` returns `authenticated: false` → redirect to LoginPage
- If Google token expired → backend auto-refreshes before API call
- If refresh token invalid (revoked) → return 401 → frontend redirects to login
- Network errors → toast notification in UI
- Empty results → friendly empty state illustration + message


## Environment Variables (.env)

```
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
SECRET_KEY=...           # For signing session cookies
REDIRECT_URI=http://localhost:8000/auth/callback
FRONTEND_URL=http://localhost:5173
```


## Out of Scope (Phase 1)

- RAG / natural language querying (Phase 2)
- Creating/editing/deleting events
- Mobile responsiveness (nice to have, not required)
- Production deployment
