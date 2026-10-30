# Typki: Product and Technical Spec

Typki is a keyboard-first desktop app for writing Anki flashcards in Typst. You type a card, see it rendered as it will appear in Anki, and save it to a deck with one shortcut. Each card is stored in Anki as SVG next to its Typst source, so any card can be reopened and edited later. Draft v0.2, October 29, 2026.

## Scope

Typki serves one workflow: deciding what is worth remembering while reading or in a lecture, and adding it straight to Anki. There is no notes document that cards are extracted from.

**Goals**

1. Capture speed: going from the new-card shortcut to a saved card takes no longer than typing the card.
2. Card quality: previews match how Anki renders the card, and automated checks flag common mistakes.
3. Editable forever: any card made in Typki can be reopened and changed, because its source lives in the Anki note.
4. One place for style: a deck's stylesheet and macros are defined once and apply to every card, old and new.
5. Small and maintainable: no sync engine and no local database of card state.

**Non-goals for v1**

- Extracting cards from Typst notes or other documents.
- Studying or reviewing cards. Anki does that.
- HTML or MathML cards. Cards are SVG only.
- Editing notes that Typki did not create. They can be viewed.
- Mobile, web, collaboration, accounts, or LaTeX input.

## Key decisions

Typki is a native Python and Qt app that renders cards with Typst, stores them in Anki as SVG, and treats Anki as the source of truth.

| Area | Choice | Reason |
| --- | --- | --- |
| Language and UI | Python 3.11+ with PySide6 (Qt 6) | Native windows, direct filesystem access, a Chromium-based preview, and fast iteration |
| Typst | The `typst` Python package, version pinned | Embeds the Typst compiler, so no separate install is needed |
| Card format | SVG rendered by Typst | Exact typography, identical on every device, no fonts needed on the phone |
| Anki connection | AnkiConnect over local HTTP | Typki never touches the collection file |
| Source of truth | Anki | Each note stores its Typst source, so there is no cache and no hand-written labels |
| Authoring model | Standalone cards | Cards are written directly, not extracted from documents |
| Style | Per-deck stylesheet and macros, plus global macros, as plain files | Versionable with git, and a change can re-render a whole deck |
| Distribution | Installable with uv or pipx | Standalone binaries are out of scope for v1 |

## Workflows

- **Capture.** With Anki running, press the new-card shortcut, pick a template, type the front and back, and watch both previews update. One shortcut saves the card to Anki and clears the form for the next one, keeping the deck, template, and tags.
- **Edit.** Search a deck, open a card, change its source, and save. The note is updated in place, so its review history is kept.
- **Restyle.** Edit a deck's stylesheet or macros while a sample card updates live. Typki shows how many cards are stale, and a dry run lists any card that no longer compiles before anything is overwritten.
- **Offline.** If Anki is closed, cards go to a local outbox and are pushed when Anki is next reachable.

## Architecture

Typki has seven modules in four layers, and every dependency points down: the ui calls the services below it, and the domain layer depends on nothing.

&#91;embedded content: module dependencies · 7 modules in 4 layers\]

A save runs the editor source through preamble resolution, the renderer, and SVG post-processing, then `addNote`. An edit reads the note with `notesInfo`, runs the same pipeline, then calls `updateNoteFields`. Only the anki, library, and render modules have side effects.

## Data model

Card state lives in Anki. Style lives in a plain-file library folder.

### Anki note type

Typki creates one note type, `Typki Card`, on first run if it is missing.

| Field | Holds | Shown |
| --- | --- | --- |
| Front | SVG for the front. First field, so Anki's duplicate check applies to it | Yes |
| Back | SVG for the back | Yes |
| FrontSrc | Typst source of the front | No |
| BackSrc | Typst source of the back | No |
| SourceId | Random UUID made at first save. Lets a retry after a partial failure find the note instead of adding a duplicate | No |
| PreambleHash | Hash of the preamble used at the last render | No |
| RendererVersion | Typst version plus Typki's render-pipeline version at the last render | No |

There is one card template. The front shows `{{Front}}`. The back shows `{{FrontSide}}`, a divider, and `{{Back}}`. The note type's CSS scales SVGs to the card width, centers them, and lets them inherit the card's text color so night mode works. Fields a user adds are ignored. Tags and decks stay Anki's own.

### Library folder

A user-chosen folder, intended to be kept under git.

```text
library/
  global/macros.typ
  decks/
    real-analysis/
      deck.toml
      macros.typ
      style.typ
  templates/definition.toml
  fonts/
  outbox/
```

Example `deck.toml`:

```toml
anki_deck = 'Real Analysis'
page_width = '105mm'
scale = 1.5
default_template = 'definition'
default_tags = ['real-analysis']
```

Child decks such as `Real Analysis::Theorems` use the nearest ancestor's config unless they have their own.

### Preamble and staleness

For each card, Typki compiles a virtual main file that imports the global macros, then the deck macros, applies the `card-style` function exported by the deck's `style.typ` as a show rule, and then includes the card source. Keeping these as separate files means compiler errors point at the right file and line.

The base preamble sets a transparent page, automatic height, the deck's page width (default 105 mm), 5 mm margins, and the default font set. PreambleHash covers the base preamble, global macros, deck macros, deck style, page width, scale, and the bundled font set. A card is stale when its stored PreambleHash or RendererVersion differs from the current ones.

## Rendering

Typki compiles each side of a card to one SVG page with a single long-lived Typst compiler, then post-processes the SVG for Anki.

1. Resolve the deck config and preamble files, including inheritance.
2. Compile the front source and the back source with the shared preamble, each to one SVG page with automatic height.
3. Post-process each SVG:
   - Theme it. Keep the page transparent and rewrite Typst's black fill and stroke to `currentColor`, so the card follows Anki's light and dark mode. Other colors stay as written.
   - Add a `desc` element holding a plain-text version of the field. Anki treats a field that contains only an SVG as empty, and flags SVG-only notes as duplicates of each other. Text inside `desc` survives Anki's tag stripping, which fixes both, and makes the card searchable.
   - Apply the deck's scale to the intrinsic width and keep the viewBox.
4. Return the SVG, diagnostics, plain text, and byte size.

**Compiler lifetime.** The app creates one compiler at startup and reuses it. In testing, creating a compiler took about 215 ms and recompiling a short card with math took 1 to 4 ms. Calling the one-shot `typst.compile` function instead repeats the startup cost on every call.

**Determinism.** The same source, preamble, and renderer version produce byte-identical SVG. System fonts are not used, only the bundled fonts and the library's `fonts` folder, so renders match across machines.

**SVG ids.** In the cards tested, SVG ids looked like content hashes, and every id shared by two cards had an identical definition. If a shared id ever has different definitions, ids are namespaced per field.

**Packages.** `@preview` imports are fetched on first use and cached. Imports are version-pinned in the source, so renders are reproducible. Offline with an uncached package, the error names the package.

## Anki integration

Typki talks to Anki only through AnkiConnect, over local HTTP, and never opens the collection file. Action availability is checked against the installed AnkiConnect version at startup.

- Setup and discovery: `version`, `deckNames`, `createDeck`, `modelNames`, `createModel`, `modelFieldNames`, `getTags`.
- Note type repair: `updateModelStyling`, `updateModelTemplates`.
- Cards: `addNote`, `canAddNotes`, `updateNoteFields`, `findNotes`, `notesInfo`, `deleteNotes`, `changeDeck`.
- Batching: `multi`, used for re-renders.

**Setup.** The user installs the AnkiConnect add-on. Typki is a native app, so no CORS configuration is needed. A first-run screen checks and explains each failure: Anki not running, add-on missing, or add-on too old.

**Note type health check.** At startup, if the note type is missing a field or template, Typki offers a repair. It never changes the note type silently.

**Failures.** Network errors are retried briefly and then shown. Saves fall back to the outbox. Batch operations report a result per note.

**Concurrency.** One user is assumed. Anki may be used between Typki sessions, so opening a card checks for drift (see Features).

## Features

P0 is needed for the first usable version, P1 follows soon after, and P2 comes later.

| Area | Requirement | Priority |
| --- | --- | --- |
| Capture | New-card form with deck, template, and tag fields, and separate front and back editors with Typst syntax highlighting | P0 |
| Capture | Live preview of both sides. On a compile error, keep the last good render and show the diagnostics | P0 |
| Capture | Save and next (clears the form, keeps deck, template, and tags) and save and stay | P0 |
| Capture | Built-in templates: Definition, Theorem, Name the theorem, Hypotheses, Proof idea, Example or counterexample, Formula, Blank. Each is a pair of Typst skeletons with placeholders | P0 |
| Capture | Drafts autosaved locally, so a crash loses nothing | P0 |
| Capture | Offline outbox, flushed when AnkiConnect is reachable, with a visible count | P1 |
| Capture | User-defined templates as library files, and tag autocomplete from Anki | P1 |
| Browse | Deck browser with thumbnails, Anki search syntax, and a stale marker | P0 |
| Browse | Open a card, edit it, and save it in place | P0 |
| Browse | Drift check on open: if the stored fields differ from a fresh render, warn, then keep Typki's render or cancel | P0 |
| Browse | Delete a card, move it to another deck, and view notes Typki did not create, read-only | P1 |
| Style | Deck settings with editors for `deck.toml`, `macros.typ`, and `style.typ`, a live sample card, and an editor for global macros | P0 |
| Style | Re-render deck: a dry run compiles every card and lists failures, then only the cards that compiled are updated, in chunks. Resumable, because staleness is recomputed | P0 |
| Style | Stale count per deck, and re-render all decks after a renderer upgrade | P1 |
| Quality | Preview in a frame that uses the note type's real CSS, with light or dark mode and desktop or phone width | P0 |
| Quality | Checks beside the preview: empty back, front equal to back, content wider than the page, excessive height, SVG over its size budget, duplicate front in the deck | P1 |
| Quality | Optional AI-assisted review of a card, for example whether it tests one fact. Off by default | P2 |
| Ergonomics | Configurable shortcut for every P0 action. Defaults: Ctrl+Enter save and next, Ctrl+Shift+Enter save and stay, Ctrl+N new card, Ctrl+Down jump to the back editor | P0 |
| Ergonomics | Command palette | P2 |

## Engineering

Typki is typed, tested Python, with side effects confined to a few modules.

- **Stack.** Python 3.11+, PySide6 (Qt 6) including Qt WebEngine for the preview, the `typst` package, pytest with pytest-qt, ruff, and a type checker. There are no other runtime dependencies: AnkiConnect is plain HTTP through the standard library, and the Typst editor's syntax highlighting is a small `QSyntaxHighlighter` covering markup, math, and code modes.
- **Performance targets.** Preview updates within 100 ms of an edit for a typical card, cold start under 3 seconds, and a 1,000-card re-render under 2 minutes, dominated by AnkiConnect round trips. M0 confirms these.
- **Threading.** Compiles and AnkiConnect calls run off the UI thread. Compiles are debounced after edits, and results from superseded edits are discarded.
- **No data loss.** Drafts are autosaved locally, and no Anki field is overwritten unless the compile succeeded.
- **Privacy.** No telemetry and no accounts. Network access is limited to localhost AnkiConnect and the Typst package registry.
- **Maintainability.** Small modules named for what they do, explicit types, no hidden global state, and comments that explain why rather than what. Side effects live only in the Anki gateway, the library store, and the renderer.
- **Testing.** Unit tests for domain logic, golden-file tests for SVG post-processing, gateway tests against a fake AnkiConnect server, headless Qt smoke tests for the main flows, and a manual device checklist for visuals: Anki desktop in light and dark mode, a phone, and a tablet.
- **Compatibility.** Current Anki desktop for authoring. AnkiDroid and AnkiMobile for review only.

Module layout:

```text
typki/
  domain/     card, deck, template, preamble, staleness
  render/     compiler, svg_postprocess, plain_text
  anki/       gateway (interface), ankiconnect, note_type, fake_anki
  library/    store, deck_config
  rerender/   plan, runner
  checks/     card_checks
  ui/         main_window, editor, preview, browser, deck_settings, shortcuts
tests/
```

## Milestones

M0 is a feasibility spike that settles the main technical risks before any UI work. Each later milestone ends with an acceptance test.

1. **M0: Feasibility spike.** Compile a hard-coded card with display math and a diagram using one long-lived compiler, and push its SVG into a throwaway Anki note. Accept when it looks right on Anki desktop (light and dark) and on a phone, front and back render correctly together on the answer side, Anki's empty and duplicate checks pass, a card that imports a macro file and a `@preview` package compiles, system fonts can be turned off, `changeDeck` exists, and compile time, SVG size, and the AnkiConnect action list are recorded.
2. **M1: Round trip.** The note type is created, and the new-card form, preview, first templates, save, deck browser with search, and open-and-edit with the drift check all work. Accept when 20 cards can be created, the app closed and reopened, and three cards edited, with no duplicates in Anki and review history kept on the edited cards.
3. **M2: Style and re-render.** Deck settings, global and deck macros, deck stylesheets, re-render with a dry run, and the CSS-accurate preview. Accept when changing a macro used by 50 cards and applying the re-render updates all 50, and a deliberately broken macro is reported in the dry run with no card overwritten.
4. **M3: Browse, quality, and outbox.** The remaining P1 features. Accept when cards saved while Anki is closed appear in Anki once it starts, without duplicates, and the card checks flag a set of deliberately bad cards.
5. **M4: Packaging.** Installation with uv or pipx and a first-run screen that guides AnkiConnect setup. Accept when a fresh install on a clean machine reaches a saved card without outside instructions.

## Open decisions

Each item has a default that this spec assumes until it is changed.

1. **Cloze.** Anki's cloze type works only on text, so an SVG cloze means Typki renders one front and back pair per deletion. Each pair is its own note, linked by SourceId, and editing the source regenerates the siblings. This is the one place where one source maps to many notes. Default: not in v1.
2. **Plain text for `desc`.** Typst has no built-in way to turn arbitrary content into a string. The options are a heuristic that strips the source, a helper function in the preamble, or reading text from the compiled document. Default: the heuristic, revisited if search quality is poor.
3. **Collection size.** A short card side measured 36 to 59 KB of SVG in testing, so thousands of cards could add up to hundreds of MB of field data before compression. Default: measure at M0, set a per-card size budget, and deduplicate repeated glyph outlines if needed.
4. **SVG on mobile.** Inline SVG with `currentColor` must work on AnkiDroid and AnkiMobile. Default: test at M0. A failure needs a different theming approach before M1.
5. **Macro imports.** The compiler must resolve imports of macro files from the library folder when the main file is generated in memory. Default: M0 checks how the binding handles this and falls back to writing the generated main file into a cache folder inside the library.
6. **Diagnostics.** The binding's errors may carry only message text. Default: show file and line when available and the raw message otherwise. M0 records what the binding returns.
7. **Typst upgrades.** The `typst` package is pinned and its version is recorded in RendererVersion, so an upgrade marks every card stale until it is re-rendered. Default: upgrade deliberately, never automatically.
8. **Moving cards between decks.** Depends on AnkiConnect's `changeDeck` action. Default: verify at M0, and drop the feature from v1 if it is missing.
