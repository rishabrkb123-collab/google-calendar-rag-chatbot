import json
import re
from typing import Any

import httpx


_EMBED_CACHE: dict[tuple[str, str], list[float]] = {}


class OllamaClientError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str, chat_model: str, embed_model: str):
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model
        self.embed_model = embed_model

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.post(
                f"{self.base_url}{path}",
                json=payload,
                timeout=httpx.Timeout(180.0, connect=15.0),
            )
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise OllamaClientError(
                "Ollama is not reachable. Start Ollama and make sure the local API is available."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaClientError(
                f"Ollama request failed with status {exc.response.status_code}: {exc.response.text}"
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
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise OllamaClientError(
                "Ollama is not reachable. Start Ollama and make sure the local API is available."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaClientError(
                f"Ollama readiness check failed with status {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaClientError(f"Ollama readiness check failed: {exc}") from exc

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise OllamaClientError("Ollama returned invalid JSON.") from exc

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        uncached_texts: list[str] = []
        uncached_keys: list[tuple[str, str]] = []
        for text in texts:
            key = (self.embed_model, text)
            if key not in _EMBED_CACHE:
                uncached_texts.append(text)
                uncached_keys.append(key)

        if uncached_texts:
            response = self._post(
                "/api/embed",
                {
                    "model": self.embed_model,
                    "input": uncached_texts,
                },
            )
            embeddings = response.get("embeddings", [])
            if len(embeddings) != len(uncached_texts):
                raise OllamaClientError(
                    "Ollama returned an unexpected embedding payload."
                )

            for key, embedding in zip(uncached_keys, embeddings):
                _EMBED_CACHE[key] = embedding

        return [_EMBED_CACHE[(self.embed_model, text)] for text in texts]

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
        # Direct parse first.
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        # Some models add preamble/postamble text around the JSON object.
        # Try to extract the outermost {...} block.
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
