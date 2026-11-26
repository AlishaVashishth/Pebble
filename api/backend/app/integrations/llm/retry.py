"""Transient retry utility for LLM providers."""

import logging
import random
import time
from typing import Any, Callable, Set
import httpx

logger = logging.getLogger(__name__)

TRANSIENT_STATUS_CODES: Set[int] = {429, 500, 502, 503, 504}


def execute_with_retry(
    fn: Callable[[], Any],
    max_retries: int = 2,
    base_delay: float = 0.5,
    max_delay: float = 3.0,
    provider_name: str = "LLMProvider",
) -> Any:
    """Execute a callable with exponential backoff on transient HTTP and network errors.

    Retries only on HTTP 429, 500, 502, 503, 504 and network/timeout exceptions.
    Never retries infinitely and never logs sensitive prompts or API keys.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else 0
            if status_code not in TRANSIENT_STATUS_CODES or attempt >= max_retries:
                logger.error(
                    f"{provider_name} request failed with HTTP {status_code} "
                    f"(attempt {attempt + 1}/{max_retries + 1}): {type(exc).__name__}"
                )
                raise
            attempt += 1
            delay = min(base_delay * (2 ** (attempt - 1)) + random.uniform(0.05, 0.2), max_delay)
            logger.warning(
                f"{provider_name} transient HTTP {status_code}; retrying in {delay:.2f}s "
                f"(attempt {attempt}/{max_retries})..."
            )
            time.sleep(delay)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            if attempt >= max_retries:
                logger.error(
                    f"{provider_name} network/timeout failure "
                    f"(attempt {attempt + 1}/{max_retries + 1}): {type(exc).__name__}"
                )
                raise
            attempt += 1
            delay = min(base_delay * (2 ** (attempt - 1)) + random.uniform(0.05, 0.2), max_delay)
            logger.warning(
                f"{provider_name} network/timeout error; retrying in {delay:.2f}s "
                f"(attempt {attempt}/{max_retries})..."
            )
            time.sleep(delay)
