"""Groq API client — drop-in replacement for OllamaClient.

Uses Groq's OpenAI-compatible chat endpoint for planning and answering.
Embeddings are implemented as lightweight bag-of-words TF vectors so the
RAG ranking pipeline continues to work without a separate embeddings model.
"""

import json
import math
import re
from collections import Counter
from typing import Any

import httpx

from backend.ollama_client import OllamaClientError


class GroqClient:
    _BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self, api_key: str, chat_model: str):
        self.api_key = api_key
        self.chat_model = chat_model
        # embed_model attribute kept for interface compatibility
        self.embed_model = "bow-tfidf"
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
    # Embeddings — lightweight bag-of-words cosine-compatible vectors.
    # Not as powerful as nomic-embed-text but avoids any external API
    # call and works well for short calendar event text.
    # ------------------------------------------------------------------
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        tokenized: list[Counter] = []
        for text in texts:
            tokens = re.findall(r"[a-z0-9]+", text.lower())
            tokenized.append(Counter(tokens))

        # Shared vocabulary across all texts in this batch.
        vocab: list[str] = sorted({tok for c in tokenized for tok in c})
        if not vocab:
            return [[0.0] for _ in texts]

        vocab_index = {tok: i for i, tok in enumerate(vocab)}
        embeddings: list[list[float]] = []
        for counter in tokenized:
            vec = [0.0] * len(vocab)
            for tok, cnt in counter.items():
                if tok in vocab_index:
                    vec[vocab_index[tok]] = float(cnt)
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                vec = [v / norm for v in vec]
            embeddings.append(vec)

        return embeddings

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
