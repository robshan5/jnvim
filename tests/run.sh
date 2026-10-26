#!/bin/sh
# Run every test.  JNVIM_PYTHON should point at a python with jupyter_client
# and ipykernel installed (defaults to python3).
set -e
cd "$(dirname "$0")/.."
PY=${JNVIM_PYTHON:-python3}

echo "--- python"
"$PY" tests/test_python.py

echo "--- neovim (cells, commands, keymaps)"
JNVIM_PYTHON="$PY" nvim --headless --clean -u tests/minimal_init.lua -l tests/spec_cells.lua

echo "--- neovim (notebook + live kernel)"
JNVIM_PYTHON="$PY" nvim --headless --clean -u tests/minimal_init.lua -l tests/spec.lua
