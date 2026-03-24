from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol
from urllib.error import URLError
from urllib.request import Request, urlopen


class TickerLookupTransportError(Exception):
    """Raised when HTTP transport cannot fetch remote ticker payloads."""


class TickerHttpClient(Protocol):
    """Transport contract for retrieving textual payloads from remote endpoints."""

    def fetch_text(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> str: ...


class UrlopenTickerHttpClient:
    """Default HTTP transport backed by ``urllib.request.urlopen``."""

    def fetch_text(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> str:
        """Fetch response payload text from URL using provided headers and timeout."""
        request = Request(url, headers=dict(headers))
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                raw_body = bytes(response.read())
                return raw_body.decode("utf-8", errors="replace")
        except (OSError, TimeoutError, URLError) as exc:
            raise TickerLookupTransportError("HTTP transport failed") from exc
