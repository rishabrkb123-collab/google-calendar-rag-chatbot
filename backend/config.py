import json
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
ENV_PATH = BACKEND_DIR / ".env"
DEFAULT_REDIRECT_URI = "http://localhost:8000/auth/callback"
DEFAULT_FRONTEND_URL = "http://localhost:5173"
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_CHAT_MODEL = "llama3.1:8b"
DEFAULT_OLLAMA_EMBED_MODEL = "nomic-embed-text"
DEFAULT_SAMPLE_QUESTIONS_FILE = PROJECT_ROOT / "google_calendar_rag_1000_questions.txt"
DEFAULT_ACTION_SAMPLE_QUESTIONS_DIR = PROJECT_ROOT / "rag_samples"
DEFAULT_CHROMA_DB_PATH = BACKEND_DIR / "chroma_db"

# Load environment variables once from the backend-specific .env file.
load_dotenv(dotenv_path=ENV_PATH, override=True)


def _candidate_credentials_paths() -> list[Path]:
    paths: list[Path] = []

    configured_path = os.getenv("GOOGLE_CLIENT_SECRETS_FILE", "").strip()
    if configured_path:
        path = Path(configured_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        paths.append(path)

    paths.extend(
        [
            PROJECT_ROOT / "google api sredentials - google calender RAG.json",
            PROJECT_ROOT / "credentials.json",
            BACKEND_DIR / "credentials.json",
        ]
    )
    return paths


@lru_cache(maxsize=1)
def _load_google_client_file() -> dict:
    for path in _candidate_credentials_paths():
        if not path.exists():
            continue

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        section = payload.get("web") or payload.get("installed") or {}
        if not section.get("client_id"):
            continue

        redirect_uris = section.get("redirect_uris") or []
        return {
            "source": str(path),
            "client_id": section.get("client_id", ""),
            "client_secret": section.get("client_secret", ""),
            "redirect_uri": redirect_uris[0] if redirect_uris else "",
        }

    return {"source": None, "client_id": "", "client_secret": "", "redirect_uri": ""}


def get_google_oauth_config() -> dict:
    file_config = _load_google_client_file()
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip() or file_config["client_id"]
    client_secret = (
        os.getenv("GOOGLE_CLIENT_SECRET", "").strip() or file_config["client_secret"]
    )
    redirect_uri = (
        os.getenv("REDIRECT_URI", "").strip()
        or file_config["redirect_uri"]
        or DEFAULT_REDIRECT_URI
    )

    source = "env"
    if not os.getenv("GOOGLE_CLIENT_ID", "").strip() and file_config["client_id"]:
        source = file_config["source"] or "credentials_file"

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "source": source,
        "credentials_file": file_config["source"],
    }


def get_frontend_url() -> str:
    return os.getenv("FRONTEND_URL", DEFAULT_FRONTEND_URL)


def get_secret_key() -> str:
    return os.getenv("SECRET_KEY", "dev-secret-change-me")


def get_ollama_config() -> dict:
    return {
        "base_url": os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
        "chat_model": os.getenv("OLLAMA_CHAT_MODEL", DEFAULT_OLLAMA_CHAT_MODEL),
        "embed_model": os.getenv("OLLAMA_EMBED_MODEL", DEFAULT_OLLAMA_EMBED_MODEL),
    }


def get_groq_config() -> dict:
    return {
        "api_key": os.getenv("GROQ_API_KEY", "").strip(),
        "chat_model": os.getenv("GROQ_CHAT_MODEL", "llama-3.3-70b-versatile"),
    }


def get_sample_questions_path() -> Path:
    configured_path = os.getenv("RAG_SAMPLE_QUESTIONS_FILE", "").strip()
    if configured_path:
        path = Path(configured_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path
    return DEFAULT_SAMPLE_QUESTIONS_FILE


def get_action_sample_questions_dir() -> Path:
    configured_path = os.getenv("RAG_ACTION_SAMPLE_DIR", "").strip()
    if configured_path:
        path = Path(configured_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path
    return DEFAULT_ACTION_SAMPLE_QUESTIONS_DIR


def get_chroma_db_path() -> Path:
    configured = os.getenv("CHROMA_DB_PATH", "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else PROJECT_ROOT / path
    return DEFAULT_CHROMA_DB_PATH
