#!/bin/sh
set -eu

SOURCE="${TYPKI_SOURCE:-git+https://github.com/andrewblodgett/typki}"

if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv, which Typki uses to manage Python..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="${XDG_BIN_HOME:-$HOME/.local/bin}:$PATH"
fi

uv tool install --reinstall "$SOURCE"
"$(uv tool dir --bin)/typki" --install-launcher >/dev/null
echo "Typki is installed. Open it from your app launcher, or run: typki"
