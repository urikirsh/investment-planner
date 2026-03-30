from __future__ import annotations

from collections.abc import Mapping

from portfolio_core.market_data.models import TickerLookupCommunicationError
from portfolio_core.market_data.transport import TickerHttpClient


class _BaseHttpLookupProvider:
    """Shared transport helper for lookup providers backed by HTTP text payloads."""

    def __init__(self, *, http_client: TickerHttpClient, request_headers: Mapping[str, str]) -> None:
        self._http_client = http_client
        self._request_headers = request_headers

    def _fetch_text_or_raise_communication_error(
        self,
        *,
        url: str,
        timeout_seconds: float,
        error_message: str,
    ) -> str:
        """Fetch payload and normalize transport failures to communication errors."""
        try:
            return self._http_client.fetch_text(
                url=url,
                headers=self._request_headers,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            raise TickerLookupCommunicationError(f"{error_message}: {exc}") from exc
