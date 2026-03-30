"""HTTP transport seam for market-data lookup providers.

This module defines:
- a typed protocol used by providers to fetch text payloads from remote URLs
- a transport-level error type used to normalize I/O failures
- the default ``urllib``-based implementation used in production

Responsibilities are limited to HTTP request/response mechanics and timeout/header
handling. Parsing and domain-level error mapping are handled by provider/service
layers.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol
from urllib.error import HTTPError, URLError
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
        except HTTPError as exc:
            raise TickerLookupTransportError(_describe_http_error(url=url, exc=exc)) from exc
        except (OSError, TimeoutError, URLError) as exc:
            raise TickerLookupTransportError(_describe_transport_error(url=url, exc=exc)) from exc


def _describe_http_error(*, url: str, exc: HTTPError) -> str:
    """Return a concise transport message for HTTP status failures."""
    return f"HTTP {exc.code} from {url}"


def _describe_transport_error(*, url: str, exc: OSError | TimeoutError | URLError) -> str:
    """Return a concise transport message for non-HTTP response failures.

    Timeout-like failures are normalized to a consistent "timed out" message so
    higher layers can surface stable user-facing diagnostics across the
    different exception types ``urllib`` may raise.
    """
    if isinstance(exc, TimeoutError):
        return f"HTTP transport timed out for {url}"
    if isinstance(exc, URLError):
        reason = exc.reason
        reason_text = str(reason).strip() if reason is not None else ""
        if reason_text and "timed out" in reason_text.lower():
            return f"HTTP transport timed out for {url}"
        if reason_text:
            return f"HTTP transport failed for {url}: {reason_text}"
        return f"HTTP transport failed for {url}"
    detail = str(exc).strip()
    if detail and "timed out" in detail.lower():
        return f"HTTP transport timed out for {url}"
    if detail:
        return f"HTTP transport failed for {url}: {detail}"
    return f"HTTP transport failed for {url}"
