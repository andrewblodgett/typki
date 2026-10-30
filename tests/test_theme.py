import re

from typki.ui.theme import THEMES

HEX_COLOR = re.compile(r"^#[0-9a-f]{6}$")


def test_theme_names_are_unique() -> None:
    names = [theme.name for theme in THEMES]
    assert len(names) == len(set(names))


def test_theme_colors_are_hex() -> None:
    for theme in THEMES:
        for field, value in vars(theme).items():
            if field not in ("name", "dark"):
                assert HEX_COLOR.match(value), f"{theme.name}.{field} = {value}"


def test_dark_themes_come_before_light_themes() -> None:
    darkness = [theme.dark for theme in THEMES]
    assert darkness == sorted(darkness, reverse=True)
