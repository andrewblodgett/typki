from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

from typki.library.store import Library

CHANGE_DEBOUNCE_MS = 150


class LibraryWatcher(QObject):
    changed = Signal()

    def __init__(self, library: Library, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.library = library
        self.watcher = QFileSystemWatcher(self)
        self.debounce = QTimer(self, singleShot=True, interval=CHANGE_DEBOUNCE_MS)
        self.debounce.timeout.connect(self.emit_change)
        self.watcher.fileChanged.connect(self.on_raw_change)
        self.watcher.directoryChanged.connect(self.on_raw_change)
        self.refresh_paths()

    def refresh_paths(self) -> None:
        wanted = {str(path) for path in self.library.watched_paths()}
        current = set(self.watcher.files()) | set(self.watcher.directories())
        stale = sorted(current - wanted)
        missing = sorted(wanted - current)
        if stale:
            self.watcher.removePaths(stale)
        if missing:
            self.watcher.addPaths(missing)

    def on_raw_change(self, _path: str) -> None:
        self.debounce.start()

    def emit_change(self) -> None:
        self.refresh_paths()
        self.changed.emit()
