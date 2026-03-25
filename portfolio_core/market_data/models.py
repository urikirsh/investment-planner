"""Domain models for market-data ticker lookup results.

This module defines the typed result contracts shared across providers, service,
and UI layers:
- the communication-level error used for lookup failures
- immutable metadata for resolved tickers
- success/not-found result payload types

It is responsible for preserving immutability guarantees on provider metadata
via deep-freeze normalization, while keeping provider/service orchestration logic
out of the model layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from portfolio_core.domain.models import Exchange


class TickerLookupCommunicationError(Exception):
    """Raised when ticker lookup cannot complete due to transport/parsing failures."""


@dataclass(frozen=True)
class TickerLookupMetadata:
    """Canonical metadata returned for a resolved ticker."""

    exchange: Exchange
    canonical_ticker: str
    display_name: str
    isin: str | None = None
    currency: str | None = None
    provider_data: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze provider metadata into an immutable mapping."""
        object.__setattr__(self, "provider_data", _deep_freeze_mapping(self.provider_data))


@dataclass(frozen=True)
class TickerLookupFound:
    """Resolved payload for successful ticker lookup."""

    metadata: TickerLookupMetadata

    @property
    def instrument_name(self) -> str:
        """Backward-compatible alias for display name used by existing callers."""
        return self.metadata.display_name


@dataclass(frozen=True)
class TickerLookupNotFound:
    """Resolved payload for missing/unsupported ticker lookup."""


TickerLookupResult = TickerLookupFound | TickerLookupNotFound


def _deep_freeze_mapping(raw: Mapping[str, object]) -> Mapping[str, object]:
    """Return recursively immutable metadata mapping."""
    return MappingProxyType({key: _deep_freeze_value(value) for key, value in raw.items()})


def _deep_freeze_value(value: object) -> object:
    """Return recursively immutable metadata value."""
    if isinstance(value, Mapping):
        normalized_mapping: dict[str, object] = {}
        for key, nested_value in value.items():
            if isinstance(key, str):
                normalized_mapping[key] = _deep_freeze_value(nested_value)
        return MappingProxyType(normalized_mapping)
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze_value(item) for item in value)
    return value
