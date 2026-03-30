from __future__ import annotations

"""Focused lifecycle tests for welcome startup market-data worker/thread management."""

from typing import Any, cast

import pytest

import ui.controllers.startup_transition as transition_mod


class _FakeSignal:
    def __init__(self) -> None:
        self.callbacks: list[Any] = []

    def connect(self, callback: Any) -> None:
        self.callbacks.append(callback)


class _FakeThread:
    def __init__(self, parent: object) -> None:
        self.parent = parent
        self.started = _FakeSignal()
        self.finished = _FakeSignal()
        self.start_called = False
        self.quit_called = False
        self.delete_later_called = False
        self.wait_called_with: int | None = None
        self.running = True
        self.wait_result = True

    def start(self) -> None:
        self.start_called = True

    def quit(self) -> None:
        self.quit_called = True

    def deleteLater(self) -> None:
        self.delete_later_called = True

    def isRunning(self) -> bool:
        return self.running

    def wait(self, timeout_ms: int) -> bool:
        self.wait_called_with = timeout_ms
        return self.wait_result


class _FakeWorker:
    def __init__(self, *, portfolio: object, cached_quote: object, timeout_seconds: float) -> None:
        self.portfolio = portfolio
        self.cached_quote = cached_quote
        self.timeout_seconds = timeout_seconds
        self.finished = _FakeSignal()
        self.moved_to_thread: object | None = None
        self.delete_later_called = False

    def moveToThread(self, thread: object) -> None:
        self.moved_to_thread = thread

    def run(self) -> None:
        return None

    def deleteLater(self) -> None:
        self.delete_later_called = True


class _FakeResultRelay:
    def __init__(self, *, on_finished: Any, parent: object) -> None:
        self.on_finished = on_finished
        self.parent = parent

    def dispatch(self, quote_obj: object, portfolio_obj: object, error_obj: object) -> None:
        self.on_finished(quote_obj, portfolio_obj, error_obj)


def test_startup_market_data_lifecycle_start_wires_and_starts_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transition_mod, "QThread", _FakeThread)
    monkeypatch.setattr(transition_mod, "StartupMarketDataWorker", _FakeWorker)
    monkeypatch.setattr(transition_mod, "StartupMarketDataResultRelay", _FakeResultRelay)

    lifecycle = transition_mod.StartupMarketDataLifecycle()
    parent = object()

    def on_finished(_quote_obj: object, _portfolio_obj: object, _error_obj: object) -> None:
        return None

    lifecycle.start(
        parent=cast(Any, parent),
        portfolio=cast(Any, "portfolio"),
        cached_quote=cast(Any, "cached-quote"),
        on_finished=on_finished,
        timeout_seconds=12.5,
    )

    assert isinstance(lifecycle.thread, _FakeThread)
    assert isinstance(lifecycle.worker, _FakeWorker)
    assert isinstance(lifecycle.result_relay, _FakeResultRelay)
    thread = lifecycle.thread
    worker = lifecycle.worker
    result_relay = lifecycle.result_relay
    assert thread.parent is parent
    assert worker.portfolio == "portfolio"
    assert worker.cached_quote == "cached-quote"
    assert worker.timeout_seconds == 12.5
    assert result_relay.parent is parent
    assert result_relay.on_finished is on_finished
    assert worker.moved_to_thread is thread
    assert thread.start_called is True
    assert any(getattr(cb, "__name__", "") == "run" for cb in thread.started.callbacks)
    assert any(getattr(cb, "__self__", None) is result_relay and getattr(cb, "__name__", "") == "dispatch" for cb in worker.finished.callbacks)
    assert any(getattr(cb, "__self__", None) is thread and getattr(cb, "__name__", "") == "quit" for cb in worker.finished.callbacks)
    assert any(getattr(cb, "__self__", None) is worker and getattr(cb, "__name__", "") == "deleteLater" for cb in worker.finished.callbacks)
    assert any(getattr(cb, "__self__", None) is thread and getattr(cb, "__name__", "") == "deleteLater" for cb in thread.finished.callbacks)


def test_startup_market_data_lifecycle_cancel_returns_false_when_wait_times_out() -> None:
    thread = _FakeThread(parent=object())
    thread.running = True
    thread.wait_result = False
    worker = _FakeWorker(portfolio=None, cached_quote=None, timeout_seconds=1.0)
    result_relay = _FakeResultRelay(on_finished=lambda *_args: None, parent=object())
    lifecycle = transition_mod.StartupMarketDataLifecycle(
        thread=cast(Any, thread),
        worker=cast(Any, worker),
        result_relay=cast(Any, result_relay),
    )

    result = lifecycle.cancel(wait_timeout_ms=77)

    assert result is False
    assert thread.quit_called is True
    assert thread.wait_called_with == 77
    assert cast(Any, lifecycle.thread) is thread
    assert cast(Any, lifecycle.worker) is worker
    assert cast(Any, lifecycle.result_relay) is result_relay
    assert worker.delete_later_called is False


def test_startup_market_data_lifecycle_cancel_clears_refs_after_successful_stop() -> None:
    thread = _FakeThread(parent=object())
    thread.running = True
    thread.wait_result = True
    worker = _FakeWorker(portfolio=None, cached_quote=None, timeout_seconds=1.0)
    lifecycle = transition_mod.StartupMarketDataLifecycle(
        thread=cast(Any, thread),
        worker=cast(Any, worker),
        result_relay=cast(Any, _FakeResultRelay(on_finished=lambda *_args: None, parent=object())),
    )

    result = lifecycle.cancel(wait_timeout_ms=55)

    assert result is True
    assert thread.quit_called is True
    assert thread.wait_called_with == 55
    assert worker.delete_later_called is True
    assert lifecycle.thread is None
    assert lifecycle.worker is None
    assert lifecycle.result_relay is None


def test_startup_market_data_lifecycle_clear_resets_thread_and_worker_refs() -> None:
    lifecycle = transition_mod.StartupMarketDataLifecycle(
        thread=cast(Any, _FakeThread(parent=object())),
        worker=cast(Any, _FakeWorker(portfolio=None, cached_quote=None, timeout_seconds=2.0)),
        result_relay=cast(Any, _FakeResultRelay(on_finished=lambda *_args: None, parent=object())),
    )

    lifecycle.clear()

    assert lifecycle.thread is None
    assert lifecycle.worker is None
    assert lifecycle.result_relay is None
