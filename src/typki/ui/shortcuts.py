import tomllib
from dataclasses import dataclass
from pathlib import Path

SETTINGS_FILENAME = "settings.toml"


@dataclass(frozen=True)
class ShortcutAction:
    key: str
    label: str
    default: str


SHORTCUT_ACTIONS: tuple[ShortcutAction, ...] = (
    ShortcutAction("save_and_next", "Save and next", "Ctrl+Return"),
    ShortcutAction("save_and_stay", "Save and stay", "Ctrl+Shift+Return"),
    ShortcutAction("new_card", "New card", "Ctrl+N"),
    ShortcutAction("focus_back", "Jump to back editor", "Ctrl+Down"),
    ShortcutAction("focus_front", "Jump to front editor", "Ctrl+Up"),
    ShortcutAction("focus_deck", "Choose deck", "Ctrl+D"),
    ShortcutAction("focus_template", "Choose template", "Ctrl+T"),
    ShortcutAction("focus_tags", "Edit tags", "Ctrl+G"),
    ShortcutAction("show_capture", "Show capture", "Ctrl+1"),
    ShortcutAction("show_browse", "Show browser", "Ctrl+2"),
    ShortcutAction("show_style", "Show deck style", "Ctrl+3"),
    ShortcutAction("search", "Search cards", "Ctrl+F"),
    ShortcutAction("toggle_dark", "Toggle dark preview", "Ctrl+Shift+D"),
    ShortcutAction("toggle_phone", "Toggle phone-width preview", "Ctrl+Shift+P"),
)


def load_shortcuts(library_root: Path) -> tuple[dict[str, str], list[str]]:
    shortcuts = {action.key: action.default for action in SHORTCUT_ACTIONS}
    problems: list[str] = []
    settings_path = library_root / SETTINGS_FILENAME
    if not settings_path.is_file():
        return shortcuts, problems
    try:
        overrides = tomllib.loads(settings_path.read_text()).get("shortcuts", {})
    except (tomllib.TOMLDecodeError, OSError) as error:
        return shortcuts, [f"{SETTINGS_FILENAME}: {error}"]
    for key, value in overrides.items():
        if key not in shortcuts:
            problems.append(f"{SETTINGS_FILENAME}: unknown shortcut '{key}'")
        elif not isinstance(value, str):
            problems.append(f"{SETTINGS_FILENAME}: shortcut '{key}' must be a string")
        else:
            shortcuts[key] = value
    return shortcuts, problems
