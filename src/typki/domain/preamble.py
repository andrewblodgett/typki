import hashlib
from dataclasses import dataclass

PREAMBLE_FORMAT_VERSION = 3
HEADER_FILENAME = "header.typ"

DEFAULT_HEADER = """#set page(width: auto, height: auto, margin: 6pt, fill: none)
#set text(font: "New Computer Modern", size: 16pt)

#show math.equation.where(block: true): equation => layout(region => {
  let width = measure(equation).width
  if width > region.width { scale(region.width / width * 100%, reflow: true, equation) } else { equation }
})

#show: body => context {
  let max-width = 120mm
  block(width: calc.min(measure(body).width, max-width), body)
}

#let Definition(term, body) = [*Definition* (#term). #body]
#let Theorem(name, statement) = [*Theorem* (#name). #emph(statement)]
"""


@dataclass(frozen=True)
class Preamble:
    header: str
    hash: str
    font_fingerprint: str = ""

    @property
    def line_count(self) -> int:
        return self.header.count("\n")

    def wrap(self, card_source: str) -> str:
        return self.header + card_source


def normalized_header(header_text: str) -> str:
    return header_text if header_text.endswith("\n") or not header_text else header_text + "\n"


def compute_preamble_hash(header: str, font_fingerprint: str) -> str:
    digest = hashlib.sha256()
    digest.update(f"format:{PREAMBLE_FORMAT_VERSION}\n".encode())
    digest.update(header.encode())
    digest.update(f"fonts:{font_fingerprint}\n".encode())
    return digest.hexdigest()[:16]


def build_preamble(header_text: str, font_fingerprint: str) -> Preamble:
    header = normalized_header(header_text)
    return Preamble(
        header=header, hash=compute_preamble_hash(header, font_fingerprint), font_fingerprint=font_fingerprint
    )
