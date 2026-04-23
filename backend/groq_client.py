"""Groq API client — drop-in replacement for OllamaClient."""

import json
import re
from typing import Any

import httpx

from backend.ollama_client import OllamaClientError


class GroqClient:
    _BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self, api_key: str, chat_model: str):
        self.api_key = api_key
        self.chat_model = chat_model
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def ensure_ready(self) -> dict[str, Any]:
        try:
            response = httpx.get(
                f"{self._BASE_URL}/models",
                headers=self._headers,
                timeout=httpx.Timeout(15.0, connect=10.0),
            )
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise OllamaClientError(
                "Groq API is not reachable. Check your internet connection."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaClientError(
                f"Groq API returned status {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaClientError(f"Groq request failed: {exc}") from exc

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise OllamaClientError("Groq returned invalid JSON.") from exc

        return {"models": [{"name": m["id"]} for m in data.get("data", [])]}

    # ------------------------------------------------------------------
    # Chat helpers
    # ------------------------------------------------------------------
    def _chat_completion(
        self,
        messages: list[dict[str, str]],
        format_json: bool = False,
        temperature: float = 0.1,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.chat_model,
            "messages": messages,
            "temperature": temperature,
        }
        if format_json:
            payload["response_format"] = {"type": "json_object"}

        try:
            response = httpx.post(
                f"{self._BASE_URL}/chat/completions",
                json=payload,
                headers=self._headers,
                timeout=httpx.Timeout(120.0, connect=15.0),
            )
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise OllamaClientError(
                "Groq API is not reachable. Check your internet connection."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaClientError(
                f"Groq request failed with status {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaClientError(f"Groq request failed: {exc}") from exc

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise OllamaClientError("Groq returned invalid JSON.") from exc

        return (
            data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        )

    def chat_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        content = self._chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            format_json=True,
            temperature=0.1,
        )
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
            f"Groq returned invalid JSON content: {content[:500]}"
        )

    def chat_text(self, system_prompt: str, user_prompt: str) -> str:
        return self._chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            format_json=False,
            temperature=0.2,
        )
