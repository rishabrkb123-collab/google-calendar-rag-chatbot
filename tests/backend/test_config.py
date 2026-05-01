from backend import config


def test_get_frontend_url_defaults_to_render_external_url(monkeypatch):
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "google-calendar-rag-chatbot.onrender.com")

    assert config.get_frontend_url() == "https://google-calendar-rag-chatbot.onrender.com"


def test_get_google_oauth_config_uses_render_url_for_redirect(monkeypatch):
    config._load_google_client_file.cache_clear()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.delenv("REDIRECT_URI", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://google-calendar-rag-chatbot.onrender.com")

    try:
        oauth_config = config.get_google_oauth_config()
    finally:
        config._load_google_client_file.cache_clear()

    assert (
        oauth_config["redirect_uri"]
        == "https://google-calendar-rag-chatbot.onrender.com/auth/callback"
    )


def test_get_session_https_only_defaults_true_on_render(monkeypatch):
    monkeypatch.delenv("SESSION_HTTPS_ONLY", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://google-calendar-rag-chatbot.onrender.com")

    assert config.get_session_https_only() is True


def test_get_session_https_only_honors_explicit_override(monkeypatch):
    monkeypatch.setenv("SESSION_HTTPS_ONLY", "false")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://google-calendar-rag-chatbot.onrender.com")

    assert config.get_session_https_only() is False


def test_get_ollama_config_uses_cloud_defaults(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_CHAT_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)

    ollama_config = config.get_ollama_config()

    assert ollama_config["base_url"] == "https://ollama.com"
    assert ollama_config["chat_model"] == "gpt-oss:20b"
    assert ollama_config["api_key"] == ""
