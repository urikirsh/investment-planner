from __future__ import annotations

"""Async ticker-lookup coordinator for add-instrument wizard flows."""

from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import QObject, QThread, Signal, Slot

from portfolio_core.market_data import (
    TickerLookupCommunicationError,
    TickerLookupFound,
    TickerLookupMetadata,
    TickerLookupResult,
)
from portfolio_core.domain.models import Exchange


@dataclass(frozen=True)
class TickerLookupSuccessOutcome:
    """Successful ticker verification payload emitted to UI consumers."""

    metadata: TickerLookupMetadata


@dataclass(frozen=True)
class TickerLookupErrorOutcome:
    """Failed ticker verification payload emitted to UI consumers."""

    message_title: str
    message_text: str


class TickerLookupChecker(Protocol):
    """Typed callable contract for ticker lookup workers."""

    def __call__(self, *, exchange: Exchange, ticker: str) -> TickerLookupResult: ...


def build_internal_error_outcome() -> TickerLookupErrorOutcome:
    """Build outcome payload for unexpected internal lookup failures."""
    return TickerLookupErrorOutcome(
        message_title="Ticker lookup internal error",
        message_text=(
            "Could not verify this ticker due to an internal error. "
            "Please try again or restart the app."
        ),
    )


class _TickerLookupWorker(QObject):
    """Background worker that verifies ticker existence on selected exchange."""

    success = Signal(object)
    error = Signal(object)

    def __init__(
        self,
        *,
        exchange: Exchange,
        ticker: str,
        checker: TickerLookupChecker,
    ) -> None:
        super().__init__()
        self._exchange = exchange
        self._ticker = ticker
        self._checker = checker

    @staticmethod
    def _network_error_outcome() -> TickerLookupErrorOutcome:
        """Build outcome payload for network/communication lookup failures."""
        return TickerLookupErrorOutcome(
            message_title="Ticker lookup network error",
            message_text=(
                "Could not verify this ticker due to a network/communication issue. "
                "Please check your connection and try again."
            ),
        )

    @staticmethod
    def _not_found_outcome() -> TickerLookupErrorOutcome:
        """Build outcome payload for missing symbol on selected exchange."""
        return TickerLookupErrorOutcome(
            message_title="Ticker not found",
            message_text="Ticker was not found on the selected exchange. Please review and try again.",
        )

    @Slot()
    def run(self) -> None:
        """Run blocking ticker lookup and emit typed outcome for UI thread handling."""
        try:
            result = self._checker(exchange=self._exchange, ticker=self._ticker)
        except TickerLookupCommunicationError:
            self.error.emit(self._network_error_outcome())
            return
        except Exception:
            self.error.emit(build_internal_error_outcome())
            return

        if isinstance(result, TickerLookupFound):
            self.success.emit(TickerLookupSuccessOutcome(metadata=result.metadata))
            return
        self.error.emit(self._not_found_outcome())


class TickerLookupCoordinator(QObject):
    """Own worker/thread lifecycle for async ticker verification."""

    started = Signal()
    success = Signal(object)
    error = Signal(object)
    stopped = Signal()

    def __init__(
        self,
        *,
        checker: TickerLookupChecker,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._checker = checker
        self._thread: QThread | None = None
        self._worker: _TickerLookupWorker | None = None

    @property
    def is_running(self) -> bool:
        """Return whether lookup worker thread is currently active."""
        return self._thread is not None

    def start_lookup(self, *, exchange: Exchange, ticker: str) -> bool:
        """Start async lookup if idle; return whether a new lookup was started."""
        if self._thread is not None:
            return False
        worker = _TickerLookupWorker(
            exchange=exchange,
            ticker=ticker,
            checker=self._checker,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self.success.emit)
        worker.error.connect(self.error.emit)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(self._on_thread_finished)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._worker = worker
        self._thread = thread
        thread.start()
        self.started.emit()
        return True

    @Slot()
    def _on_thread_finished(self) -> None:
        """Clear lifecycle references and notify consumers when lookup stops."""
        self._worker = None
        self._thread = None
        self.stopped.emit()
