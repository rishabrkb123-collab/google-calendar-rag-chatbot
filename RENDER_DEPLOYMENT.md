# Render Deployment Guide

## Deployment shape

This project deploys to Render as a single Python web service:

- FastAPI serves the API
- the React frontend is built during the Render build step
- FastAPI serves the built frontend from `frontend/dist`
- Ollama Cloud is used as the LLM backend

## Files already prepared

- `render.yaml`: Render Blueprint config
- `render.env.example`: env template for Render
- `backend/.env.example`: local/dev env template

## Important note about env files on Render

Render does not automatically read a repo `.env` file into service environment variables.

What is already set up now:

- `render.yaml` declares every required Render env key so Render can detect them during Blueprint setup
- the app auto-derives `FRONTEND_URL` and `REDIRECT_URI` from Render's built-in `RENDER_EXTERNAL_URL`
- `render.env.example` gives you a ready-to-paste env file for the Render dashboard

## Required Render environment variables

Set these in Render:

```env
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret
SECRET_KEY=replace-with-a-long-random-secret
OLLAMA_API_KEY=your-ollama-cloud-api-key
```

You can use `render.env.example` as the source.

## Render Blueprint settings

The checked-in `render.yaml` now uses:

- runtime: Python 3.11
- build command: install backend deps, install frontend deps, build frontend
- start command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
- health check: `/health`

## Deploy steps on Render

1. Push this repository to GitHub.
2. In Render, choose `New +` -> `Blueprint`.
3. Select this repository: `https://github.com/rishabrkb123-collab/google-calendar-rag-chatbot`
4. Render will detect `render.yaml` automatically.
5. Fill in the missing env vars from `render.env.example`.
6. Create the service.

## Google OAuth setup for Render

After Render gives you the public app URL, update Google Cloud Console OAuth settings.

If your Render URL is:

```text
https://google-calendar-rag-chatbot.onrender.com
```

then add:

- Authorized JavaScript origin:
  - `https://google-calendar-rag-chatbot.onrender.com`
- Authorized redirect URI:
  - `https://google-calendar-rag-chatbot.onrender.com/auth/callback`

Because the app now derives public URLs from `RENDER_EXTERNAL_URL`, you do not need to hardcode `FRONTEND_URL` or `REDIRECT_URI` in Render unless you want to override them.

## Ollama Cloud setup

This deployment assumes Ollama Cloud, not a local Ollama server.

Use:

- `OLLAMA_API_KEY=<your key>`

The app now defaults to:

- `OLLAMA_BASE_URL=https://ollama.com`
- `OLLAMA_CHAT_MODEL=gpt-oss:20b`
- secure session cookies on Render

## Health check

Render should report the service healthy when:

```text
GET /health
```

returns:

```json
{"status":"ok"}
```

## Post-deploy verification

After deploy:

1. Open the Render URL.
2. Click sign-in and verify Google OAuth redirects back to `/dashboard`.
3. Check `https://<your-render-url>/chat/health`.
4. Ask a simple chat question like `What do I have today?`
5. Test one create/update/delete flow.

## Notes

- Chroma data is stored on Render's ephemeral filesystem by default. That is fine for this project because the sample corpus can be re-seeded automatically.
- If you later want persistent vector storage across restarts, add a Render disk and point `CHROMA_DB_PATH` to it.
