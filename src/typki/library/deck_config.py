import json
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path

from typki.domain.deck import (
    DEFAULT_FIT_WIDTH,
    DEFAULT_PAGE_WIDTH,
    DEFAULT_SCALE,
    DEFAULT_TEMPLATE,
    DeckConfig,
)

DECK_CONFIG_FILENAME = "deck.toml"


class DeckConfigError(ValueError):
    pass


def parse_deck_config(text: str, folder: str, source_label: str) -> DeckConfig:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise DeckConfigError(f"{source_label}: {error}") from error
    anki_deck = data.get("anki_deck")
    if not isinstance(anki_deck, str) or not anki_deck.strip():
        raise DeckConfigError(f"{source_label}: anki_deck must be a non-empty string")
    scale = data.get("scale", DEFAULT_SCALE)
    if not isinstance(scale, (int, float)) or scale <= 0:
        raise DeckConfigError(f"{source_label}: scale must be a positive number")
    fit_width = data.get("fit_width", DEFAULT_FIT_WIDTH)
    if not isinstance(fit_width, bool):
        raise DeckConfigError(f"{source_label}: fit_width must be true or false")
    tags = data.get("default_tags", [])
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise DeckConfigError(f"{source_label}: default_tags must be a list of strings")
    return DeckConfig(
        anki_deck=anki_deck.strip(),
        page_width=str(data.get("page_width", DEFAULT_PAGE_WIDTH)),
        scale=float(scale),
        default_template=str(data.get("default_template", DEFAULT_TEMPLATE)),
        default_tags=tuple(tags),
        fit_width=fit_width,
        folder=folder,
    )


def load_deck_configs(decks_dir: Path) -> tuple[dict[str, DeckConfig], list[str]]:
    configs: dict[str, DeckConfig] = {}
    problems: list[str] = []
    if not decks_dir.is_dir():
        return configs, problems
    for config_path in sorted(decks_dir.glob(f"*/{DECK_CONFIG_FILENAME}")):
        folder = config_path.parent.name
        try:
            config = parse_deck_config(
                config_path.read_text(), folder, f"decks/{folder}/{DECK_CONFIG_FILENAME}"
            )
        except (DeckConfigError, OSError) as error:
            problems.append(str(error))
            continue
        if config.anki_deck in configs:
            problems.append(
                f"decks/{folder}/{DECK_CONFIG_FILENAME}: deck '{config.anki_deck}' is already configured "
                f"by decks/{configs[config.anki_deck].folder}"
            )
            continue
        configs[config.anki_deck] = config
    return configs, problems


TomlValue = str | float | bool | list[str]


def toml_value(value: TomlValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}" if "." in f"{value:g}" else f"{value:g}.0"
    if isinstance(value, list):
        return "[" + ", ".join(json.dumps(item, ensure_ascii=False) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False)


def update_toml_keys(text: str, updates: Mapping[str, TomlValue]) -> str:
    lines = text.splitlines()
    remaining = dict(updates)
    for index, line in enumerate(lines):
        match = re.match(r"^\s*([A-Za-z0-9_-]+)\s*=", line)
        if match and match.group(1) in remaining:
            key = match.group(1)
            lines[index] = f"{key} = {toml_value(remaining.pop(key))}"
    lines.extend(f"{key} = {toml_value(value)}" for key, value in remaining.items())
    return "\n".join(lines) + "\n"


def deck_config_values(config: DeckConfig) -> dict[str, TomlValue]:
    return {
        "anki_deck": config.anki_deck,
        "page_width": config.page_width,
        "fit_width": config.fit_width,
        "scale": float(config.scale),
        "default_template": config.default_template,
        "default_tags": list(config.default_tags),
    }
