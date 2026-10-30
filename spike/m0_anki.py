import json
import re
import time
import urllib.request
import uuid
from xml.sax.saxutils import escape

import typst

from m0_render import (
    BACK_SOURCE,
    FRONT_SOURCE,
    LIBRARY,
    PACKAGE_CACHE,
    compile_card,
)

ANKICONNECT_URL = "http://127.0.0.1:8765"
MODEL_NAME = "Typki Card (spike)"
DECK_NAME = "Typki Spike"
MOVED_DECK_NAME = "Typki Spike::Moved"
FIELD_NAMES = ["Front", "Back", "FrontSrc", "BackSrc", "SourceId", "PreambleHash", "RendererVersion"]
SCALE = 1.5

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

FRONT_TEMPLATE = "{{Front}}"
BACK_TEMPLATE = "{{FrontSide}}<hr id=answer>{{Back}}"


def invoke(action, **params):
    payload = json.dumps({"action": action, "version": 6, "params": params}).encode()
    start = time.perf_counter()
    with urllib.request.urlopen(urllib.request.Request(ANKICONNECT_URL, payload)) as response:
        body = response.read()
    elapsed_ms = (time.perf_counter() - start) * 1000
    reply = json.loads(body)
    if reply["error"] is not None:
        raise RuntimeError(f"{action}: {reply['error']}")
    return reply["result"], elapsed_ms, len(body)


def call(action, **params):
    return invoke(action, **params)[0]


def plain_text_from_source(source):
    without_imports = re.sub(r"^#import.*$", "", source, flags=re.M)
    without_code_blocks = re.sub(r"#\w+(\.\w+)*\(\{.*?\}\)", "", without_imports, flags=re.S)
    without_hashes = re.sub(r"#\w+", "", without_code_blocks)
    without_punctuation = re.sub(r"[\[\]$*_{}()\\]", " ", without_hashes)
    return re.sub(r"\s+", " ", without_punctuation).strip()


def postprocess_svg(svg_bytes, plain_text, scale):
    svg_text = svg_bytes.decode()
    svg_text = re.sub(r'(fill|stroke)="#000000"', r'\1="currentColor"', svg_text)

    def scale_dimension(match):
        return f'{match.group(1)}="{float(match.group(2)) * scale:.3f}pt"'

    opening_tag_end = svg_text.index(">") + 1
    opening_tag = re.sub(r'(width|height)="([\d.]+)pt"', scale_dimension, svg_text[:opening_tag_end])
    description = f"<desc>{escape(plain_text)}</desc>" if plain_text else ""
    return opening_tag + description + svg_text[opening_tag_end:]


def ensure_model():
    if MODEL_NAME in call("modelNames"):
        call("updateModelStyling", model={"name": MODEL_NAME, "css": CARD_CSS})
        return
    call(
        "createModel",
        modelName=MODEL_NAME,
        inOrderFields=FIELD_NAMES,
        css=CARD_CSS,
        isCloze=False,
        cardTemplates=[{"Name": "Card 1", "Front": FRONT_TEMPLATE, "Back": BACK_TEMPLATE}],
    )


def note_payload(front_svg, back_svg, front_source="", back_source="", source_id=None):
    return {
        "deckName": DECK_NAME,
        "modelName": MODEL_NAME,
        "fields": {
            "Front": front_svg,
            "Back": back_svg,
            "FrontSrc": front_source,
            "BackSrc": back_source,
            "SourceId": source_id or str(uuid.uuid4()),
            "PreambleHash": "spike-hash-1",
            "RendererVersion": "typst-py-0.15.0+typki-0",
        },
        "tags": ["typki-spike"],
    }


def check_empty_and_duplicate_rules(compiler):
    svg_a, _ = compile_card(compiler, "Alpha card")
    svg_b, _ = compile_card(compiler, "Beta card")
    bare_a = postprocess_svg(svg_a, "", SCALE)
    bare_b = postprocess_svg(svg_b, "", SCALE)
    described_a = postprocess_svg(svg_a, "Alpha card", SCALE)
    described_b = postprocess_svg(svg_b, "Beta card", SCALE)

    bare_check = call("canAddNotesWithErrorDetail", notes=[note_payload(bare_a, bare_b)])
    print(f"bare svg front (no desc), addable: {bare_check}")
    described_check = call("canAddNotesWithErrorDetail", notes=[note_payload(described_a, described_b)])
    print(f"svg front with desc, addable: {described_check}")

    probe_id = call("addNote", note=note_payload(described_a, described_b))
    duplicate_check = call(
        "canAddNotesWithErrorDetail",
        notes=[note_payload(described_b, described_a), note_payload(described_a, described_b)],
    )
    print(f"after adding Alpha: [Beta front, Alpha front] addable: {duplicate_check}")
    call("deleteNotes", notes=[probe_id])


def main():
    print(f"ankiconnect version: {call('version')}")
    call("createDeck", deck=DECK_NAME)
    call("createDeck", deck=MOVED_DECK_NAME)
    ensure_model()
    print(f"model fields: {call('modelFieldNames', modelName=MODEL_NAME)}")

    compiler = typst.Compiler(
        root=str(LIBRARY), ignore_system_fonts=True, package_cache_path=str(PACKAGE_CACHE)
    )
    check_empty_and_duplicate_rules(compiler)

    front_raw, _ = compile_card(compiler, FRONT_SOURCE)
    back_raw, _ = compile_card(compiler, BACK_SOURCE)
    front_svg = postprocess_svg(front_raw, plain_text_from_source(FRONT_SOURCE), SCALE)
    back_svg = postprocess_svg(back_raw, plain_text_from_source(BACK_SOURCE), SCALE)
    print(f"front desc: {plain_text_from_source(FRONT_SOURCE)!r}")
    print(f"back desc: {plain_text_from_source(BACK_SOURCE)!r}")

    source_id = str(uuid.uuid4())
    note_id, add_ms, _ = invoke(
        "addNote", note=note_payload(front_svg, back_svg, FRONT_SOURCE, BACK_SOURCE, source_id)
    )
    print(f"addNote: id {note_id} in {add_ms:.1f} ms")

    found = call("findNotes", query=f'"note:{MODEL_NAME}" SourceId:{source_id}')
    print(f"findNotes by SourceId: {found}")
    stale = call("findNotes", query=f'"note:{MODEL_NAME}" -PreambleHash:spike-hash-2')
    print(f"findNotes stale query (hash != spike-hash-2): {len(stale)} notes")

    info, info_ms, info_bytes = invoke("notesInfo", notes=[note_id])
    stored_fields = info[0]["fields"]
    print(f"notesInfo: {info_ms:.1f} ms, {info_bytes} bytes")
    print(f"stored Front byte-identical: {stored_fields['Front']['value'] == front_svg}")
    print(f"stored Back byte-identical: {stored_fields['Back']['value'] == back_svg}")
    print(f"stored FrontSrc byte-identical: {stored_fields['FrontSrc']['value'] == FRONT_SOURCE}")

    mod_times = call("notesModTime", notes=[note_id])
    print(f"notesModTime: {mod_times}")

    card_ids = info[0]["cards"]
    call("changeDeck", cards=card_ids, deck=MOVED_DECK_NAME)
    moved_deck = call("cardsInfo", cards=card_ids)[0]["deckName"]
    call("changeDeck", cards=card_ids, deck=DECK_NAME)
    print(f"changeDeck: moved to {moved_deck!r} and back")

    _, update_ms, _ = invoke(
        "updateNoteFields", note={"id": note_id, "fields": {"PreambleHash": "spike-hash-2"}}
    )
    reread = call("notesInfo", notes=[note_id])[0]["fields"]["PreambleHash"]["value"]
    print(f"updateNoteFields: {update_ms:.1f} ms, PreambleHash now {reread!r}")

    batch_payload = [
        {"action": "updateNoteFields", "params": {"note": {"id": note_id, "fields": {"Front": front_svg}}}}
        for _ in range(50)
    ]
    _, multi_ms, _ = invoke("multi", actions=batch_payload)
    print(f"multi with 50 full-SVG updates: {multi_ms:.1f} ms ({multi_ms / 50:.1f} ms each)")

    answer_html = call("cardsInfo", cards=card_ids)[0]["answer"]
    print(f"rendered answer html length: {len(answer_html)}, contains two svgs: {answer_html.count('<svg') == 2}")
    print(f"\nnote left in deck {DECK_NAME!r} for visual checks: note id {note_id}")


if __name__ == "__main__":
    main()
