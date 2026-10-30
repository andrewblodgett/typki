import re
from dataclasses import dataclass

PLACEHOLDER_PATTERN = re.compile(r"«[^«»\n]*»")


@dataclass(frozen=True)
class Template:
    key: str
    title: str
    front: str
    back: str


BUILT_IN_TEMPLATES: tuple[Template, ...] = (
    Template("definition", "Definition", "*Define* «term».", "«term» is «definition»."),
    Template("theorem", "Theorem", "State *«theorem name»*.", "*Theorem.* «statement»"),
    Template(
        "name-the-theorem",
        "Name the theorem",
        "Which theorem says: «statement»",
        "*«theorem name»*",
    ),
    Template(
        "hypotheses",
        "Hypotheses",
        "What are the hypotheses of *«theorem name»*?",
        "+ «hypothesis»\n+ «hypothesis»",
    ),
    Template("proof-idea", "Proof idea", "Proof idea of *«theorem name»*?", "«key idea»"),
    Template(
        "example",
        "Example or counterexample",
        "Give an example of «object» that is «property» but not «property».",
        "«example»",
    ),
    Template("formula", "Formula", "«quantity» $=$ ?", "$ «formula» $"),
    Template("blank", "Blank", "", ""),
)


def find_template(key: str, templates: tuple[Template, ...] = BUILT_IN_TEMPLATES) -> Template:
    by_key = {template.key: template for template in templates}
    return by_key.get(key) or by_key.get("blank") or templates[0]


def placeholder_spans(text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in PLACEHOLDER_PATTERN.finditer(text)]
