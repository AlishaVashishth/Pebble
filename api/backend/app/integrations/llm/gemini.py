"""Google Gemini LLM completion provider implementation."""

import logging
from typing import Optional
import httpx

from backend.app.integrations.llm.base import LLMProvider
from backend.app.integrations.llm.retry import execute_with_retry

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    """Google Gemini completion provider using the Generative Language REST API."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-1.5-flash",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Call Gemini generateContent endpoint with structured JSON generation."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}],
                }
            ],
            "systemInstruction": {
                "parts": [{"text": system_prompt}],
            },
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.1,
                "maxOutputTokens": 2048,
            },
        }

        def _do_request() -> str:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                candidates = data.get("candidates")
                if not candidates:
                    raise RuntimeError("Gemini response contained no candidates")
                parts = candidates[0].get("content", {}).get("parts", [])
                if not parts:
                    raise RuntimeError("Gemini candidate contained no parts")
                return parts[0].get("text", "")

        return execute_with_retry(_do_request, provider_name="GeminiProvider")
