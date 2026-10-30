import threading

from PySide6.QtCore import QObject, Signal

from typki.rerender.runner import Rerenderer, RerenderProgress, RerenderReport
from typki.ui.background import TaskRunner


class BackgroundRerender(QObject):
    state_changed = Signal()
    progressed = Signal(object)

    def __init__(self, rerenderer: Rerenderer, runner: TaskRunner, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.rerenderer = rerenderer
        self.runner = runner
        self.running = False
        self.pending = False
        self.cancel = threading.Event()
        self.done = 0
        self.total = 0
        self.failed = 0
        self.progressed.connect(self.on_progress)

    def request(self) -> None:
        if self.running:
            self.pending = True
            self.cancel.set()
            return
        self.running = True
        self.cancel = threading.Event()
        cancel = self.cancel
        self.runner.run(lambda: self.run_job(cancel), self.on_finished, lambda _error: self.on_finished(None))

    def run_job(self, cancel: threading.Event) -> RerenderReport | None:
        stale = self.rerenderer.staleness().stale_note_ids
        if not stale:
            return None
        return self.rerenderer.run(stale, apply=True, progress=self.progressed.emit, cancel=cancel)

    def on_progress(self, progress: RerenderProgress) -> None:
        self.done, self.total = progress.done, progress.total
        self.state_changed.emit()

    def on_finished(self, report: RerenderReport | None) -> None:
        self.running = False
        self.done = self.total = 0
        if report is not None and not report.cancelled:
            self.failed = len(report.failures)
        elif report is None:
            self.failed = 0
        self.state_changed.emit()
        if self.pending:
            self.pending = False
            self.request()
