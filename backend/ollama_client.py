import json
import re
from typing import Any

import httpx


class OllamaClientError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str, chat_model: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model
        self.api_key = api_key

    @property
    def _headers(self) -> dict[str, str]:
        headers = {
            "ngrok-skip-browser-warning": "true",
            "User-Agent": "Mozilla/5.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.post(
                f"{self.base_url}{path}",
                json=payload,
                headers=self._headers,
                timeout=httpx.Timeout(180.0, connect=15.0),
            )
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise OllamaClientError(
                "Ollama is not reachable. Make sure the Ollama app/server is running and OLLAMA_BASE_URL is correct."
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                raise OllamaClientError(
                    "Ollama API key is invalid or missing. Set OLLAMA_API_KEY in backend/.env"
                ) from exc
            raise OllamaClientError(
                f"Ollama request failed with status {status}: {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaClientError(f"Ollama request failed: {exc}") from exc

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise OllamaClientError("Ollama returned invalid JSON.") from exc

    def ensure_ready(self) -> dict[str, Any]:
        try:
            response = httpx.get(
                f"{self.base_url}/api/tags",
                headers=self._headers,
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise OllamaClientError(
                "Ollama is not reachable. Make sure the Ollama app/server is running and OLLAMA_BASE_URL is correct."
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                raise OllamaClientError(
                    "Ollama API key is invalid or missing. Set OLLAMA_API_KEY in backend/.env"
                ) from exc
            if status in (404, 405):
                return {"models": [{"name": self.chat_model}]}
            raise OllamaClientError(
                f"Ollama readiness check failed with status {status}: {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaClientError(f"Ollama readiness check failed: {exc}") from exc

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise OllamaClientError("Ollama returned invalid JSON.") from exc

        if not data.get("models") and self.chat_model:
            data["models"] = [{"name": self.chat_model}]
        return data

    def chat_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        response = self._post(
            "/api/chat",
            {
                "model": self.chat_model,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        content = response.get("message", {}).get("content", "{}")
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        raise OllamaClientError(
            f"Ollama returned invalid JSON content: {content[:500]}"
        )

    def chat_text(self, system_prompt: str, user_prompt: str) -> str:
        response = self._post(
            "/api/chat",
            {
                "model": self.chat_model,
                "stream": False,
                "options": {"temperature": 0.2},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        return response.get("message", {}).get("content", "").strip()
