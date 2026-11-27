"""Azure OpenAI chat completion provider implementation."""

import logging
from typing import Optional
import httpx

from backend.app.integrations.llm.base import LLMProvider
from backend.app.integrations.llm.retry import execute_with_retry

logger = logging.getLogger(__name__)


class AzureOpenAIProvider(LLMProvider):
    """Azure OpenAI completion provider using REST API with httpx."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        deployment: str,
        api_version: str = "2024-02-15-preview",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.deployment = deployment
        self.api_version = api_version
        self.timeout_seconds = timeout_seconds

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Call Azure OpenAI chat completions endpoint with automatic transient retry."""
        url = f"{self.endpoint}/openai/deployments/{self.deployment}/chat/completions?api-version={self.api_version}"
        headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
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
                    raise RuntimeError("Azure OpenAI response contained no choices")
                return choices[0].get("message", {}).get("content", "")

        return execute_with_retry(_do_request, provider_name="AzureOpenAIProvider")
