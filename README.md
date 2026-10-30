# typki

## why
I had claude make this for me to harness the power of two great pieces of software. Anki, the king of spaced review flashcards, has an incredible algorithm for helping me memorize stuff for eternity. It has atrocious UI though, and the majority of the stuff I want to remember is math/physics stuff that is a pain to type out in LaTeX, especially at in-class speeds. I also am very opinionated about how things should be typeset, and the default MathJAX stuff that goes on in Anki is not very fun. Typst is basically just LaTeX but actually pleasant to use and much faster and better in every way, but lacks support in Anki because of its novelty.

There are already a couple projects out there that integrate typst into anki, but none of them were exactly what I wanted; they aim more for converting your notes into flashcards. I don't take notes though in the traditional sense, I only write down the most important things and save them as spaced review flashcards so that I'll remember them forever, and I wanted software to facilitate that. But luckily tokens are cheap, so claude cooked up this little app where you can do all your flashcards directly in typst and it will save them as SVG into your anki deck. 

## Installing

Typki has only been tested on Linux. You'll also need [Anki](https://apps.ankiweb.net) (the desktop app).

Install Typki with:

```sh
curl -LsSf https://raw.githubusercontent.com/andrewblodgett/typki/main/install.sh | sh
```

This installs [uv](https://docs.astral.sh/uv/) if you don't have it (uv also fetches the Python version Typki needs), installs Typki, and adds it to your app launcher. Open Typki from the launcher like any other app, or run `typki` in a terminal.

To update, run `uv tool upgrade typki`. To uninstall, run `uv tool uninstall typki` and delete `~/.local/share/applications/typki.desktop`.

If you already have uv, `uv tool install git+https://github.com/andrewblodgett/typki` does the same thing; Typki adds itself to the launcher the first time you run it.

### For development

```sh
git clone https://github.com/andrewblodgett/typki.git
cd typki
uv tool install --editable .
```

Run `typki` once to add it to your launcher. An editable install runs the code in your clone directly, so changes take effect the next time you open Typki. If you change the dependencies, run `uv tool install --editable . --reinstall`. Run the tests with `uv run pytest`.

## Setting up

**Connect to Anki.** Typki talks to Anki through the AnkiConnect add-on. In Anki, choose **Tools → Add-ons → Get Add-ons…**, enter `2055492159`, and restart Anki. On first launch, Typki walks you through this and connects automatically once Anki is running. Keep Anki open while you use Typki. If it's closed, cards are queued and sent once Anki is back.

**Your library.** Typki keeps its files in `~/typki-library`:

- `header.typ` is the Typst header added to every card: page setup, fonts, and your own macros. Edit it in the **Global** tab. When you leave that tab, your existing cards are re-rendered with the new header in the background.
- `fonts/` is for extra fonts your cards use.

To keep the library somewhere else (for example a synced folder), run `typki --library /path/to/folder` once; Typki remembers it.

**Templates.** Any function in the header whose name starts with a capital letter, like `#let Theorem(name, statement) = ...`, shows up in the template menu. Lowercase functions stay plain helpers.

**Trying it without Anki.** `typki --fake-anki` runs against a temporary in-memory Anki, so you can try everything without touching your real collection.