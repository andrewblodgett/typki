import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from typki.rerender.runner import Rerenderer, RerenderProgress, RerenderReport
from typki.ui.background import CoalescingTask, TaskRunner


class BackgroundRerender(QObject):
    state_changed = Signal()
    progressed = Signal(object)

    def __init__(self, rerenderer: Rerenderer, runner: TaskRunner, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.rerenderer = rerenderer
        self.cancel = threading.Event()
        self.done = self.total = self.failed = 0
        self.task = CoalescingTask(
            runner, self.make_job, self.on_finished, lambda _error: self.on_finished(None)
        )
        self.progressed.connect(self.on_progress)

    def request(self) -> None:
        self.cancel.set()
        self.task.request()

    def make_job(self) -> Callable[[], RerenderReport | None]:
        self.cancel = cancel = threading.Event()
        return lambda: self.run_job(cancel)

    def run_job(self, cancel: threading.Event) -> RerenderReport | None:
        stale = self.rerenderer.staleness().stale_note_ids
        if not stale:
            return None
        return self.rerenderer.run(stale, apply=True, progress=self.progressed.emit, cancel=cancel)

    def on_progress(self, progress: RerenderProgress) -> None:
        self.done, self.total = progress.done, progress.total
        self.state_changed.emit()

    def on_finished(self, report: RerenderReport | None) -> None:
        self.done = self.total = 0
        if report is None:
            self.failed = 0
        elif not report.cancelled:
            self.failed = len(report.failures)
        self.state_changed.emit()
