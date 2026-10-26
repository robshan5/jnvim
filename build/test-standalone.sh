#!/bin/sh
# Simulate a target machine: hide the build venv so the binary has to fall back
# to its own bundled kernel, and drive it with the system python.
set -e
cd "$(dirname "$0")/.."
[ -d .venv-build ] || { echo "no build venv to hide" >&2; exit 1; }
restore() { [ -d .venv-build.off ] && mv .venv-build.off .venv-build; }
trap restore EXIT INT TERM
mv .venv-build .venv-build.off

echo "--- kernels visible without the build venv:"
./dist/jnvim --list-kernels
echo "--- running the TUI with the system python ($(python3 -V 2>&1)):"
JNVIM_CMD="$PWD/dist/jnvim" python3 tests/tui_exec.py
