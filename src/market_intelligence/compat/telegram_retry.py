from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any


def _retry_after(response: Any) -> float | None:
    if getattr(response, "status_code", None) != 429:
        return None
    try:
        payload = response.json()
        value = payload.get("parameters", {}).get("retry_after", 1)
        return min(max(float(value), 1.0), 120.0)
    except (AttributeError, TypeError, ValueError):
        return 1.0


def _rewind_files(files: Any) -> None:
    if not isinstance(files, dict):
        return
    for item in files.values():
        handle = item[1] if isinstance(item, tuple) and len(item) > 1 else item
        seek = getattr(handle, "seek", None)
        if callable(seek):
            seek(0)


@contextmanager
def retry_legacy_telegram_posts(*, max_attempts: int = 5) -> Iterator[None]:
    """Honor Bot API 429 responses used by the strangled legacy senders."""
    import requests

    original_post: Callable[..., Any] = requests.post

    def post_with_retry(url: Any, *args: Any, **kwargs: Any) -> Any:
        if "api.telegram.org" not in str(url):
            return original_post(url, *args, **kwargs)
        response: Any = None
        for attempt in range(max_attempts):
            if attempt:
                _rewind_files(kwargs.get("files"))
            response = original_post(url, *args, **kwargs)
            delay = _retry_after(response)
            if delay is None or attempt == max_attempts - 1:
                return response
            time.sleep(delay)
        return response

    requests.post = post_with_retry
    try:
        yield
    finally:
        requests.post = original_post
