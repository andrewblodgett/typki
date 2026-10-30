from collections.abc import Iterator
from pathlib import Path

import pytest

from typki.anki.ankiconnect import AnkiConnectGateway
from typki.anki.fake_anki import FakeAnki, running_fake_ankiconnect
from typki.card_service import CardService
from typki.library.store import Library
from typki.render.compiler import Renderer

DECK_TOML = """anki_deck = 'Real Analysis'
page_width = '90mm'
scale = 1.25
default_template = 'definition'
default_tags = ['real-analysis']
"""


@pytest.fixture
def library(tmp_path: Path) -> Library:
    store = Library(tmp_path / "library")
    store.ensure_layout()
    (store.root / "global/macros.typ").write_text("#let RRR = $bb(R)$\n")
    deck_dir = store.root / "decks/real-analysis"
    deck_dir.mkdir(parents=True)
    (deck_dir / "deck.toml").write_text(DECK_TOML)
    (deck_dir / "macros.typ").write_text("#let defn(term, body) = [*#term.* #body]\n")
    (deck_dir / "style.typ").write_text("#let card-style(body) = { set text(size: 12pt); body }\n")
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
