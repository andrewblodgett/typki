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
FRONT_TEMPLATE = "{{Front}}"
BACK_TEMPLATE = "{{FrontSide}}\n<hr id=answer>\n{{Back}}"

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

    def describe(self) -> str:
        if not self.exists:
            return f"The note type '{NOTE_TYPE_NAME}' does not exist."
        problems = []
        if self.missing_fields:
            problems.append(f"missing fields: {', '.join(self.missing_fields)}")
        if self.templates_differ:
            problems.append("card template differs from Typki's")
        if self.styling_differs:
            problems.append("styling differs from Typki's")
        return f"The note type '{NOTE_TYPE_NAME}' has problems: " + "; ".join(problems) + "."


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
        templates_differ=(
            card_template.get("Front", "").strip() != FRONT_TEMPLATE
            or card_template.get("Back", "").strip() != BACK_TEMPLATE
        ),
        styling_differs=styling.strip() != CARD_CSS.strip(),
    )
