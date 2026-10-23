from collections.abc import Awaitable, Callable
from openai import APIStatusError, AsyncOpenAI
from openai.types.chat import ChatCompletionMessage
from typing import Any, Optional, TypeVar
import asyncio
import os
import re

LLM_MODEL = os.environ["LLM_MODEL"]
LLM_REASONING_EFFORT = os.environ.get("LLM_REASONING_EFFORT", "low")
EMBEDDING_MODEL = os.environ["EMBEDDING_MODEL"]
# Rate limited (429) or overloaded (503): both usually pass after a short wait.
TRANSIENT_STATUS_CODES = (429, 503)

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_TRANSIENT_ERROR_RETRIES = 3
_DEFAULT_RETRY_WAIT_IN_SECONDS = 15
_MAX_RETRY_WAIT_IN_SECONDS = 60

_client = AsyncOpenAI(api_key=os.environ["GEMINI_API_KEY"], base_url=_GEMINI_BASE_URL)

Response = TypeVar("Response")


async def create_chat_completion(
    messages: list[dict[str, Any]],
    tools: Optional[list[dict[str, Any]]] = None,
    model: str = LLM_MODEL,
    **options: Any,
) -> ChatCompletionMessage:
    if tools:
        options["tools"] = tools
    completion = await _request_with_retries(
        lambda: _client.chat.completions.create(
            model=model,
            messages=messages,
            **options,
        )
    )
    return completion.choices[0].message


async def create_embedding(text: str) -> list[float]:
    response = await _request_with_retries(
        lambda: _client.embeddings.create(model=EMBEDDING_MODEL, input=text)
    )
    return response.data[0].embedding


# The free tier limits requests per minute, which a single answer with several
# tool calls can exceed, and busy models answer 503. The SDK's own retries give
# up within seconds, so this waits for the window Gemini reports instead.
async def _request_with_retries(
    send_request: Callable[[], Awaitable[Response]],
) -> Response:
    for attempt in range(_TRANSIENT_ERROR_RETRIES + 1):
        try:
            return await send_request()
        except APIStatusError as error:
            wait_in_seconds = _compose_retry_wait(error)
            # A longer wait means the daily quota is gone, so waiting will not help.
            is_transient = (
                error.status_code in TRANSIENT_STATUS_CODES
                and wait_in_seconds <= _MAX_RETRY_WAIT_IN_SECONDS
            )
            if not is_transient or attempt == _TRANSIENT_ERROR_RETRIES:
                raise
            await asyncio.sleep(wait_in_seconds)


def _compose_retry_wait(error: APIStatusError) -> float:
    match = re.search(r"retry(?:Delay)?\D{0,8}?([0-9]+(?:\.[0-9]+)?)s", str(error))
    if match is None:
        return _DEFAULT_RETRY_WAIT_IN_SECONDS
    return float(match.group(1)) + 1
