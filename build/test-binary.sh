#!/bin/sh
# Exercise the built binary: pure logic, the TUI, and both kernel paths.
set -e
cd "$(dirname "$0")/.."
BIN=${BIN:-$PWD/dist/jnvim}
PY=${PY:-$PWD/.venv-build/bin/python}

"$BIN" --version
JNVIM_CMD="$BIN" "$PY" tests/tui_smoke.py
echo "--- default kernel"
JNVIM_CMD="$BIN" "$PY" tests/tui_exec.py
echo "--- bundled kernel (no system python involved)"
JNVIM_CMD="$BIN -k jnvim-python" "$PY" tests/tui_exec.py
