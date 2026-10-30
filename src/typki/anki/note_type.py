from dataclasses import dataclass

NOTE_TYPE_NAME = "Typki Card"
FRONT = "Front"
BACK = "Back"
FRONT_SOURCE = "FrontSrc"
BACK_SOURCE = "BackSrc"
SOURCE_ID = "SourceId"
PREAMBLE_HASH = "PreambleHash"
RENDERER_VERSION = "RendererVersion"
FIELD_NAMES = (FRONT, BACK, FRONT_SOURCE, BACK_SOURCE, SOURCE_ID, PREAMBLE_HASH, RENDERER_VERSION)
CARD_TEMPLATE_NAME = "Card 1"
CARD_TEMPLATE = {"Front": "{{Front}}", "Back": "{{FrontSide}}\n<hr id=answer>\n{{Back}}"}

CARD_CSS = """.card {
  font-family: sans-serif;
  text-align: center;
  color: black;
  background-color: white;
}
.nightMode.card, .night_mode .card {
  color: white;
  background-color: #2f2f31;
}
.card svg {
  display: block;
  margin: 0 auto;
  max-width: 100%;
  height: auto;
}
hr#answer {
  margin: 1em 0;
}
"""


@dataclass(frozen=True)
class NoteTypeHealth:
    exists: bool
    missing_fields: tuple[str, ...] = ()
    templates_differ: bool = False
    styling_differs: bool = False

    @property
    def healthy(self) -> bool:
        return self.exists and not (self.missing_fields or self.templates_differ or self.styling_differs)


def diagnose_note_type(
    model_names: list[str],
    field_names: list[str],
    templates: dict[str, dict[str, str]],
    styling: str,
) -> NoteTypeHealth:
    if NOTE_TYPE_NAME not in model_names:
        return NoteTypeHealth(exists=False)
    card_template = templates.get(CARD_TEMPLATE_NAME, {})
    return NoteTypeHealth(
        exists=True,
        missing_fields=tuple(name for name in FIELD_NAMES if name not in field_names),
        templates_differ=any(
            card_template.get(side, "").strip() != expected for side, expected in CARD_TEMPLATE.items()
        ),
        styling_differs=styling.strip() != CARD_CSS.strip(),
    )
