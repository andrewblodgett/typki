import hashlib
import re
import time
from pathlib import Path

import typst

SPIKE_DIR = Path(__file__).parent
LIBRARY = SPIKE_DIR / "library"
PACKAGE_CACHE = SPIKE_DIR / ".package-cache"

BASE_PREAMBLE = """#set page(width: 105mm, height: auto, margin: 5mm, fill: none)
#set text(font: "Libertinus Serif", size: 11pt)
"""

PREAMBLE_HEADER = (
    BASE_PREAMBLE
    + """#import "/global/macros.typ": *
#import "/decks/demo/macros.typ": *
#import "/decks/demo/style.typ": card-style
#show: card-style
"""
)

FRONT_SOURCE = """#defn[Uniform continuity][
  $f: A -> RR$ is uniformly continuous if
  $ forall epsilon > 0 space exists delta > 0 : abs(x - y) < delta ==> abs(f(x) - f(y)) < epsilon $
]
"""

BACK_SOURCE = """#import "@preview/cetz:0.4.2"
Every continuous function on a compact set is uniformly continuous.
#cetz.canvas({
  import cetz.draw: *
  line((0, 0), (4, 0), mark: (end: ">"))
  line((0, 0), (0, 2.5), mark: (end: ">"))
  bezier((0.2, 0.3), (3.8, 2.2), (1.5, 2.4), (2.5, 0.2))
  content((4.2, 0), $x$)
})
"""

BROKEN_SOURCE = """Line one
$ abs(x) + undefined-macro(y) $
"""


def timed(label, function):
    start = time.perf_counter()
    result = function()
    print(f"{label}: {(time.perf_counter() - start) * 1000:.1f} ms")
    return result


def compile_card(compiler, card_source):
    return compiler.compile_with_warnings(
        input=(PREAMBLE_HEADER + card_source).encode(), format="svg"
    )


def summarize_svg(label, svg_bytes):
    svg_text = svg_bytes.decode()
    ids = re.findall(r'id="([^"]+)"', svg_text)
    fills = sorted(set(re.findall(r'(?:fill|stroke)="([^"]+)"', svg_text)))
    print(f"{label}: {len(svg_bytes)} bytes, {len(ids)} ids, sample ids {ids[:3]}, colors {fills}")
    print(f"  head: {svg_text[:300]!r}")


def check_include_scoping(compiler):
    card_file = LIBRARY / ".cache" / "card.typ"
    card_file.parent.mkdir(exist_ok=True)
    card_file.write_text("$ x in RR $\n")
    main_source = BASE_PREAMBLE + '#import "/global/macros.typ": *\n#include "/.cache/card.typ"\n'
    try:
        compiler.compile(input=main_source.encode(), format="svg")
        print("include scoping: macros ARE visible in included file")
    except typst.TypstError as error:
        print(f"include scoping: macros NOT visible in included file -> {error.message}")


def check_diagnostics(compiler):
    try:
        compile_card(compiler, BROKEN_SOURCE)
    except typst.TypstError as error:
        print(f"diagnostic.message: {error.message!r}")
        print(f"diagnostic.hints: {error.hints!r}")
        print(f"diagnostic.trace: {error.trace!r}")
        print(f"diagnostic.diagnostic:\n{error.diagnostic}")
        print(f"preamble header lines: {PREAMBLE_HEADER.count(chr(10))}")


def main():
    fonts_without_system = typst.Fonts(include_system_fonts=False, font_paths=[str(LIBRARY / "fonts")])
    print(f"fonts without system: {fonts_without_system.families()}")

    compiler = timed(
        "compiler init",
        lambda: typst.Compiler(
            root=str(LIBRARY),
            font_paths=fonts_without_system,
            ignore_system_fonts=True,
            package_cache_path=str(PACKAGE_CACHE),
        ),
    )
    version_svg = compiler.compile(input=b"#sys.version", format="svg")
    print(f"typst version svg length: {len(version_svg)}")

    front_svg, front_warnings = timed("front first compile", lambda: compile_card(compiler, FRONT_SOURCE))
    back_svg, back_warnings = timed("back first compile (fetches cetz)", lambda: compile_card(compiler, BACK_SOURCE))
    for attempt in range(3):
        timed(f"front recompile {attempt}", lambda: compile_card(compiler, FRONT_SOURCE + f"\n{attempt}"))
    timed("back recompile", lambda: compile_card(compiler, BACK_SOURCE + "\nx"))
    print(f"warnings: {[w.message for w in front_warnings + back_warnings]}")

    summarize_svg("front", front_svg)
    summarize_svg("back", back_svg)

    front_again, _ = compile_card(compiler, FRONT_SOURCE)
    other_compiler = typst.Compiler(
        root=str(LIBRARY), font_paths=fonts_without_system, ignore_system_fonts=True,
        package_cache_path=str(PACKAGE_CACHE),
    )
    front_other, _ = compile_card(other_compiler, FRONT_SOURCE)
    print(f"deterministic same compiler: {front_svg == front_again}")
    print(f"deterministic fresh compiler: {front_svg == front_other}")

    front_ids = dict(re.findall(r'id="([^"]+)"(.{0,0})', front_svg.decode()))
    back_ids = dict(re.findall(r'id="([^"]+)"(.{0,0})', back_svg.decode()))
    shared = set(front_ids) & set(back_ids)
    print(f"ids shared between front and back: {len(shared)}")

    check_include_scoping(compiler)
    check_diagnostics(compiler)

    output_dir = SPIKE_DIR / "out"
    output_dir.mkdir(exist_ok=True)
    (output_dir / "front.svg").write_bytes(front_svg)
    (output_dir / "back.svg").write_bytes(back_svg)
    print(f"front sha256: {hashlib.sha256(front_svg).hexdigest()[:16]}")


if __name__ == "__main__":
    main()
