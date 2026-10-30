import json
import re
import threading
from dataclasses import dataclass, field

import typst

CATALOG_MODULES = ("std", "math", "sym", "calc")
CATALOG_SOURCE = """
#let describe(module) = dictionary(module).pairs().map(((name, value)) => {
  let kind = str(type(value))
  (
    name: name,
    kind: kind,
    glyph: if kind == "symbol" { str(value) } else { none },
    variants: if kind == "symbol" { repr(value) } else { none },
  )
})
"""
CATALOG_SOURCE += (
    f"#metadata(({', '.join(f'{name}: describe({name})' for name in CATALOG_MODULES)})) <catalog>\n"
)
VARIANT_PATTERN = re.compile(r'\(\s*"([^"]*)",\s*"((?:[^"\\]|\\.)*)"\s*\)')
CALLABLE_KINDS = frozenset({"function", "type"})


@dataclass(frozen=True)
class Entry:
    name: str
    kind: str
    glyph: str = ""
    variants: tuple[tuple[str, str], ...] = ()

    @property
    def callable(self) -> bool:
        return self.kind in CALLABLE_KINDS


@dataclass(frozen=True)
class Catalog:
    modules: dict[str, dict[str, Entry]] = field(default_factory=dict)

    def module(self, name: str) -> dict[str, Entry]:
        return self.modules.get(name, {})


def decode_glyph(raw: str) -> str:
    return re.sub(r"\\u\{([0-9a-fA-F]+)\}", lambda match: chr(int(match.group(1), 16)), raw).replace(
        '\\"', '"'
    )


def parse_variants(representation: str | None) -> tuple[tuple[str, str], ...]:
    if not representation:
        return ()
    return tuple(
        (modifiers, decode_glyph(glyph))
        for modifiers, glyph in VARIANT_PATTERN.findall(representation)
        if modifiers
    )


def parse_catalog(payload: str) -> Catalog:
    data = json.loads(payload)
    modules: dict[str, dict[str, Entry]] = {}
    for module_name, entries in data.items():
        modules[module_name] = {
            entry["name"]: Entry(
                name=entry["name"],
                kind=entry["kind"],
                glyph=entry.get("glyph") or "",
                variants=parse_variants(entry.get("variants")),
            )
            for entry in entries
        }
    return Catalog(modules)


def query_catalog() -> Catalog:
    try:
        payload = typst.query(
            CATALOG_SOURCE.encode(), "<catalog>", field="value", one=True, ignore_system_fonts=True
        )
        return parse_catalog(payload)
    except Exception:
        return Catalog()


catalog_lock = threading.Lock()
loaded_catalog: Catalog | None = None


def typst_catalog() -> Catalog:
    global loaded_catalog
    with catalog_lock:
        if loaded_catalog is None:
            loaded_catalog = query_catalog()
        return loaded_catalog


def warm_catalog_in_background() -> None:
    threading.Thread(target=typst_catalog, name="typst-catalog", daemon=True).start()
