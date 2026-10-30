import os
import re
import shutil
import sys
from pathlib import Path

APP_ID = "typki"
ICON_PATH = Path(__file__).parent / "ui" / "icon.svg"
EXEC_LINE = re.compile(r'^Exec="([^"]+)"', re.M)
DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=Typki
Comment=Write Anki flashcards in Typst
Exec="{executable}"
Icon={app_id}
Terminal=false
Categories=Education;
Keywords=anki;flashcards;typst;cards;
StartupWMClass={app_id}
"""


def ensure_launcher(executable: Path, data_dir: Path) -> None:
    if sys.platform.startswith("linux") and executable.name == APP_ID and executable.is_file():
        if not launcher_works(data_dir):
            install_launcher(executable, data_dir)


def user_data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def launcher_paths(data_dir: Path) -> tuple[Path, Path]:
    entry = data_dir / "applications" / f"{APP_ID}.desktop"
    icon = data_dir / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"
    return entry, icon


def launcher_works(data_dir: Path) -> bool:
    entry, icon = launcher_paths(data_dir)
    if not (entry.is_file() and icon.is_file()):
        return False
    match = EXEC_LINE.search(entry.read_text(encoding="utf-8"))
    return match is not None and Path(match.group(1)).is_file()


def install_launcher(executable: Path, data_dir: Path) -> tuple[Path, Path]:
    entry, icon = launcher_paths(data_dir)
    for path in (entry, icon):
        path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ICON_PATH, icon)
    entry.write_text(DESKTOP_ENTRY.format(executable=executable, app_id=APP_ID), encoding="utf-8")
    return entry, icon
