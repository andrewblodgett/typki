import os
import shutil
from pathlib import Path

APP_ID = "typki"
ICON_PATH = Path(__file__).parent / "ui" / "icon.svg"
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


def user_data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def install_launcher(executable: Path, data_dir: Path) -> tuple[Path, Path]:
    entry = data_dir / "applications" / f"{APP_ID}.desktop"
    icon = data_dir / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"
    for path in (entry, icon):
        path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ICON_PATH, icon)
    entry.write_text(DESKTOP_ENTRY.format(executable=executable, app_id=APP_ID), encoding="utf-8")
    return entry, icon
