from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtWidgets import QCompleter, QLineEdit, QWidget


class TagsEdit(QLineEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = QStringListModel(self)
        self.completer_popup = QCompleter(self.model, self)
        self.completer_popup.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer_popup.setWidget(self)
        self.completer_popup.activated.connect(self.insert_completion)
        self.textEdited.connect(self.update_completion)

    def set_known_tags(self, tags: list[str]) -> None:
        self.model.setStringList(sorted(set(tags), key=str.lower))

    def add_known_tags(self, tags: tuple[str, ...]) -> None:
        self.set_known_tags(self.model.stringList() + list(tags))

    def current_word(self) -> str:
        text = self.text()[: self.cursorPosition()]
        return "" if not text or text.endswith(" ") else text.split()[-1]

    def update_completion(self, _text: str) -> None:
        word = self.current_word()
        if not word:
            self.hide_popup()
            return
        self.completer_popup.setCompletionPrefix(word)
        if self.completer_popup.completionCount():
            self.completer_popup.complete()
        else:
            self.hide_popup()

    def hide_popup(self) -> None:
        popup = self.completer_popup.popup()
        if popup is not None:
            popup.hide()

    def insert_completion(self, completion: str) -> None:
        position = self.cursorPosition()
        before = self.text()[:position]
        after = self.text()[position:]
        before = before[: len(before) - len(self.current_word())] + completion + " "
        self.setText(before + after.lstrip())
        self.setCursorPosition(len(before))
