"""Groq LLM chat completion provider implementation."""

import logging
import httpx

from backend.app.integrations.llm.base import LLMProvider
from backend.app.integrations.llm.retry import execute_with_retry

logger = logging.getLogger(__name__)


class GroqProvider(LLMProvider):
    """Groq completion provider using REST API with httpx."""

    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.1-8b-instant",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Call Groq chat completions endpoint with automatic transient retry."""
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 2048,
            "response_format": {"type": "json_object"},
        }

        def _do_request() -> str:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                choices = data.get("choices")
                if not choices:
                    raise RuntimeError("Groq response contained no choices")
                return choices[0].get("message", {}).get("content", "")

        return execute_with_retry(_do_request, provider_name="GroqProvider")
