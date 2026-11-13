from collections.abc import Iterator
from pathlib import Path

import pytest

from typki.anki.ankiconnect import AnkiConnectGateway
from typki.anki.fake_anki import FakeAnki, running_fake_ankiconnect
from typki.card_service import CardService
from typki.library.store import Library
from typki.render.compiler import Renderer

TEST_MACROS = """#let RRR = $bb(R)$
#let defn(term, body) = [*#term.* #body]
"""


@pytest.fixture
def library(tmp_path: Path) -> Library:
    store = Library(tmp_path / "library")
    store.ensure_layout()
    store.write_header(store.read_header() + TEST_MACROS)
    return store


@pytest.fixture
def renderer(library: Library) -> Renderer:
    return Renderer(library.root, [library.fonts_dir])


@pytest.fixture
def fake_ankiconnect() -> Iterator[tuple[AnkiConnectGateway, FakeAnki]]:
    with running_fake_ankiconnect() as (url, fake):
        yield AnkiConnectGateway(url, timeout_seconds=5), fake


@pytest.fixture
def service(
    fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki], library: Library, renderer: Renderer
) -> CardService:
    gateway, _ = fake_ankiconnect
    card_service = CardService(gateway, library, renderer)
    card_service.create_note_type()
    return card_service


def replace_defn(library: Library, definition: str) -> None:
    lines = [line for line in library.read_header().splitlines() if not line.startswith("#let defn")]
    library.write_header("\n".join(lines) + "\n" + definition + "\n")
