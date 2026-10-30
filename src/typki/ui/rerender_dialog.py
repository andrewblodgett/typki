import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from typki.rerender.plan import StalenessReport
from typki.rerender.runner import (
    FailureGroup,
    Rerenderer,
    RerenderFailure,
    RerenderProgress,
    RerenderReport,
    group_failures,
)
from typki.ui.background import TaskRunner

GROUP_ROLE = Qt.ItemDataRole.UserRole


class ProgressRelay(QObject):
    progress = Signal(object)


def failure_text(failure: RerenderFailure) -> str:
    detail = failure.diagnostics[0].describe() if failure.diagnostics else failure.reason
    deck = f"{failure.deck_name} · " if failure.deck_name else ""
    return f"{failure.title}\n{deck}{detail}"


def group_text(group: FailureGroup) -> str:
    if group.diagnostic is None:
        return failure_text(group.failures[0])
    count = len(group.failures)
    affected = f"{count} card{'s' if count != 1 else ''}"
    return f"{group.diagnostic.describe()}\nAffects {affected}. Double-click to open the file at this line."


class RerenderDialog(QDialog):
    open_requested = Signal(object)
    diagnostic_requested = Signal(object)
    finished_updating = Signal()

    def __init__(
        self,
        rerenderer: Rerenderer,
        runner: TaskRunner,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.rerenderer = rerenderer
        self.runner = runner
        self.stale_note_ids: tuple[int, ...] = ()
        self.cancel_event = threading.Event()
        self.relay = ProgressRelay(self)
        self.relay.progress.connect(self.on_progress)
        self.setWindowTitle("Re-render cards")
        self.resize(640, 420)

        self.message = QLabel("Checking which cards need re-rendering…")
        self.message.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.failures = QListWidget()
        self.failures.setVisible(False)
        self.failures.setToolTip("Double-click to open the card or file and fix it.")
        self.buttons = QDialogButtonBox()
        self.apply_button = QPushButton("Update cards")
        self.apply_button.setDefault(True)
        self.cancel_button = QPushButton("Stop")
        self.close_button = self.buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self.buttons.addButton(self.cancel_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.buttons.addButton(self.apply_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_button.setVisible(False)
        self.cancel_button.setVisible(False)

        layout = QVBoxLayout(self)
        layout.addWidget(self.message)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.failures, 1)
        layout.addStretch(0)
        layout.addWidget(self.buttons)

        self.close_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self.apply)
        self.cancel_button.clicked.connect(self.cancel_event.set)
        self.failures.itemActivated.connect(self.on_failure_activated)
        self.runner.run(self.rerenderer.staleness, self.on_staleness, self.on_error)

    def on_staleness(self, report: StalenessReport) -> None:
        self.stale_note_ids = report.stale_note_ids
        if not self.stale_note_ids:
            self.progress_bar.setVisible(False)
            self.message.setText(f"All {report.total} cards are up to date. Nothing to do.")
            return
        self.message.setText(f"Checking that {len(self.stale_note_ids)} stale cards compile…")
        self.progress_bar.setRange(0, len(self.stale_note_ids))
        self.progress_bar.setValue(0)
        note_ids = self.stale_note_ids
        self.runner.run(
            lambda: self.rerenderer.run(note_ids, apply=False, progress=self.relay.progress.emit),
            self.on_dry_run,
            self.on_error,
        )

    def on_progress(self, progress: RerenderProgress) -> None:
        self.progress_bar.setRange(0, progress.total)
        self.progress_bar.setValue(progress.done)

    def show_failures(self, failures: list[RerenderFailure]) -> None:
        self.failures.clear()
        for group in group_failures(failures):
            item = QListWidgetItem(group_text(group))
            item.setData(GROUP_ROLE, group)
            if group.shared:
                item.setToolTip("\n".join(failure.title for failure in group.failures[:30]))
            self.failures.addItem(item)
        self.failures.setVisible(bool(failures))

    def on_dry_run(self, report: RerenderReport) -> None:
        self.progress_bar.setVisible(False)
        compiled = len(report.compiled)
        self.show_failures(report.failures)
        if not report.failures:
            self.message.setText(f"All {compiled} stale cards compile. Update them in Anki?")
        elif compiled:
            self.message.setText(
                f"{compiled} cards compile and can be updated. {len(report.failures)} have errors and will "
                "be left exactly as they are:"
            )
        else:
            self.message.setText(
                f"None of the {len(report.failures)} stale cards compile, so nothing can be updated:"
            )
        if compiled:
            self.apply_button.setText(f"Update {compiled} cards")
            self.apply_button.setVisible(True)
            self.apply_button.setFocus()

    def apply(self) -> None:
        self.apply_button.setVisible(False)
        self.cancel_button.setVisible(True)
        self.close_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.message.setText("Updating cards in Anki…")
        note_ids = self.stale_note_ids
        self.runner.run(
            lambda: self.rerenderer.run(
                note_ids, apply=True, progress=self.relay.progress.emit, cancel=self.cancel_event
            ),
            self.on_applied,
            self.on_error,
        )

    def on_applied(self, report: RerenderReport) -> None:
        self.cancel_button.setVisible(False)
        self.close_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.show_failures(report.failures)
        summary = f"Updated {len(report.updated)} cards."
        if report.cancelled:
            summary += " Stopped early; re-render again to finish the rest."
        if report.failures:
            summary += f" {len(report.failures)} were left unchanged:"
        self.message.setText(summary)
        self.close_button.setFocus()
        self.finished_updating.emit()

    def on_error(self, error: Exception) -> None:
        self.cancel_button.setVisible(False)
        self.close_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.message.setText(f"Something went wrong: {error}. No further cards were changed.")
        self.finished_updating.emit()

    def on_failure_activated(self, item: QListWidgetItem) -> None:
        group: FailureGroup = item.data(GROUP_ROLE)
        if group.diagnostic is not None:
            self.diagnostic_requested.emit(group.diagnostic)
        else:
            self.open_requested.emit(group.failures[0].note_id)

    def reject(self) -> None:
        if not self.close_button.isEnabled():
            self.cancel_event.set()
            return
        super().reject()
