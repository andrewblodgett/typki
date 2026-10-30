import itertools
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

SuccessCallback = Callable[[Any], None]
ErrorCallback = Callable[[Exception], None]


class _Task(QRunnable):
    def __init__(self, task_id: int, function: Callable[[], Any], runner: TaskRunner) -> None:
        super().__init__()
        self.task_id = task_id
        self.function = function
        self.runner = runner

    def run(self) -> None:
        try:
            result = self.function()
        except Exception as error:
            self.runner.finished.emit(self.task_id, False, error)
        else:
            self.runner.finished.emit(self.task_id, True, result)


class TaskRunner(QObject):
    finished = Signal(int, bool, object)

    def __init__(self, max_threads: int, default_error: ErrorCallback, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max_threads)
        self.default_error = default_error
        self.callbacks: dict[int, tuple[SuccessCallback, ErrorCallback]] = {}
        self.ids = itertools.count(1)
        self.finished.connect(self._dispatch)

    def run(
        self,
        function: Callable[[], Any],
        on_success: SuccessCallback,
        on_error: ErrorCallback | None = None,
    ) -> None:
        task_id = next(self.ids)
        self.callbacks[task_id] = (on_success, on_error or self.default_error)
        self.pool.start(_Task(task_id, function, self))

    @Slot(int, bool, object)
    def _dispatch(self, task_id: int, succeeded: bool, payload: object) -> None:
        on_success, on_error = self.callbacks.pop(task_id)
        if succeeded:
            on_success(payload)
        else:
            assert isinstance(payload, Exception)
            on_error(payload)

    def wait(self, timeout_ms: int = 5000) -> bool:
        return self.pool.waitForDone(timeout_ms)
