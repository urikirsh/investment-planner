from __future__ import annotations

"""Shared Qt worker-thread lifecycle helpers for async UI tasks."""

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from PySide6.QtCore import QObject, QThread, Slot


class SupportsWorkerThreadLifecycle(Protocol):
    """Minimal worker contract required by `QtWorkerThreadLifecycle`."""

    finished: Any

    def moveToThread(self, thread: QThread) -> bool: ...

    def run(self) -> None: ...

    def deleteLater(self) -> None: ...


class QtWorkerResultRelay(QObject):
    """Relay worker-finished payloads back onto the GUI thread."""

    def __init__(self, *, on_finished: Callable[..., None], parent: QObject) -> None:
        super().__init__(parent)
        self._on_finished = on_finished

    @Slot()
    @Slot(object)
    @Slot(object, object)
    @Slot(object, object, object)
    def dispatch(self, *args: object) -> None:
        """Forward worker results from the GUI thread to the caller callback."""
        self._on_finished(*args)


@dataclass
class QtWorkerThreadLifecycle:
    """Own `QThread` setup, GUI-thread relay wiring, and cleanup for one worker."""

    thread: QThread | None = None
    worker: SupportsWorkerThreadLifecycle | None = None
    result_relay: QtWorkerResultRelay | None = None

    def start(
        self,
        *,
        parent: QObject,
        worker: SupportsWorkerThreadLifecycle,
        on_finished: Callable[..., None],
    ) -> None:
        """Create, wire, and start a worker thread with GUI-thread result dispatch."""
        thread = QThread(parent)
        result_relay = QtWorkerResultRelay(on_finished=on_finished, parent=parent)
        self.thread = thread
        self.worker = worker
        self.result_relay = result_relay
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(result_relay.dispatch)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self.clear)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def cancel(self, *, wait_timeout_ms: int, delete_worker_on_cancel: bool = False) -> bool:
        """Stop and detach an in-flight worker thread, if any."""
        if self.thread is not None and self.thread.isRunning():
            self.thread.quit()
            if not self.thread.wait(wait_timeout_ms):
                return False
        if delete_worker_on_cancel and self.worker is not None:
            try:
                self.worker.deleteLater()
            except RuntimeError:
                pass
        self.clear()
        return True

    def clear(self) -> None:
        """Drop tracked thread/worker/relay references after shutdown."""
        self.thread = None
        self.worker = None
        self.result_relay = None
