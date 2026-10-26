#!/bin/sh
# Build a single-file Linux executable of jnvim.
#
#   sh build/build-linux.sh            # full build (bundles its own kernel)
#   JNVIM_SLIM=1 sh build/build-linux.sh   # client only, needs a system kernel
#
# The result lands in dist/jnvim.  PyInstaller does not bundle glibc, so the
# binary runs on the build machine's glibc version and newer - build on the
# oldest distro you need to support.
set -e

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

# Oracle/RHEL 7 build hosts keep a modern python in a software collection
if [ -f /opt/rh/rh-python38/enable ]; then
    # shellcheck disable=SC1091
    . /opt/rh/rh-python38/enable
fi

VENV=${VENV:-$ROOT/.venv-build}
[ -d "$VENV" ] || python3 -m venv "$VENV"
# shellcheck disable=SC1091
. "$VENV/bin/activate"

python -c "import curses" || { echo "python is missing the curses module" >&2; exit 1; }
python -m pip install --quiet --upgrade pip
python -m pip install --quiet pyinstaller jupyter_client ipykernel

KERNEL_OPTS="--collect-all ipykernel --collect-all IPython --collect-all ipython_genutils"
[ -n "$JNVIM_SLIM" ] && KERNEL_OPTS="--exclude-module ipykernel --exclude-module IPython"

# ncurses compiled here only looks in this host's terminfo path, so carry a
# small database for the terminals people actually use
TI="$ROOT/build/terminfo"
rm -rf "$TI"
mkdir -p "$TI"
TI_SRC=$(ls -d /usr/share/terminfo /lib/terminfo 2>/dev/null | head -1)
for term in xterm xterm-color xterm-256color screen screen-256color tmux \
            tmux-256color linux vt100 vt220 ansi rxvt rxvt-unicode \
            rxvt-unicode-256color putty putty-256color alacritty foot \
            st st-256color dumb; do
    src=$(find "$TI_SRC" -type f -name "$term" 2>/dev/null | head -1)
    if [ -n "$src" ]; then
        dest="$TI/$(basename "$(dirname "$src")")"
        mkdir -p "$dest"
        cp -f "$src" "$dest/"
    fi
done
echo "terminfo entries bundled: $(find "$TI" -type f | wc -l)"

rm -rf "$ROOT/build/work" "$ROOT/build/jnvim.spec" "$ROOT/dist"

# shellcheck disable=SC2086
python -m PyInstaller \
    --name jnvim \
    --onefile \
    --console \
    --noconfirm \
    --clean \
    --log-level WARN \
    --distpath "$ROOT/dist" \
    --workpath "$ROOT/build/work" \
    --specpath "$ROOT/build" \
    --paths "$ROOT" \
    --add-data "$TI:terminfo" \
    --collect-all jupyter_client \
    --collect-all jupyter_core \
    --collect-all zmq \
    --collect-all traitlets \
    --collect-all dateutil \
    $KERNEL_OPTS \
    --exclude-module debugpy \
    --exclude-module tkinter \
    --exclude-module matplotlib \
    --exclude-module numpy \
    --exclude-module PyQt5 \
    --exclude-module PySide2 \
    "$ROOT/build/entry.py"

BIN="$ROOT/dist/jnvim"
chmod +x "$BIN"

echo
echo "built: $BIN"
ls -lh "$BIN" | awk '{print "size :", $5}'
echo "glibc: $(objdump -T "$BIN" 2>/dev/null | sed -n 's/.*GLIBC_\([0-9.]*\).*/\1/p' | sort -uV | tail -1)"
"$BIN" --version
"$BIN" --list-kernels || true
