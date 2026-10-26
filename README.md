# jnvim

A terminal Jupyter notebook editor driven by vim motions. Edit `.ipynb` files,
run cells against a real Jupyter kernel and see the output inline — without
leaving the terminal and without a browser.

Linux / macOS only (it needs the `curses` module). On Windows, run it inside WSL.

```
▐ In [1] 1/3 ──────────────────────────────────────────
▐  1 │ import numpy as np
▐  2 │ print(np.arange(5).sum())
▐ Out[1] ──────────────────────────────────────────────
▐ 10

  Markdown 2/3 ───────────────────────────────────────
   1 │ ## results
```

## Install

Grab the single-file binary (see *Building a binary* below) and run it:

```sh
chmod +x jnvim
./jnvim notebook.ipynb
```

It is self-contained: no Python, no Jupyter, no pip. If the machine already has
a Jupyter kernel installed, `jnvim` uses it (so your `numpy`, `pandas`, … are
available); otherwise it falls back to the Python kernel baked into the binary.

From source instead:

```sh
pip install -e .          # pulls in jupyter_client + ipykernel
jnvim notebook.ipynb
```

Or run it straight from the source tree:

```sh
python3 -m jnvim notebook.ipynb
```

Useful flags: `-k/--kernel <name>` to pick a kernel, `--list-kernels` (the `*`
marks the one that would be used). The file is created on `:w` if it does not
exist yet.

## Two modes

`jnvim` mirrors Jupyter's split between *command* and *edit* mode, but both
are vim-flavoured.

**NOTEBOOK mode** — the cursor is a whole cell.

| key | action |
| --- | --- |
| `j` `k` `gg` `G` | move between cells (counts work: `3j`) |
| `<CR>` | edit the cell (enters cell NORMAL mode) |
| `i` `I` `a` | edit the cell and start inserting |
| `o` `O` | new code cell below / above, start inserting |
| `dd` `yy` `x` `p` `P` | delete / yank / cut / paste cells (`3dd` works) |
| `J` `K` | move the current cell down / up |
| `u` `<C-r>` | undo / redo a notebook-level edit |
| `<Space>` | run the cell and move to the next one |
| `s` | run the cell and stay |
| `A` | run every cell |
| `m` `c` `t` | change cell type to markdown / code / raw |
| `C` | clear this cell's output |
| `z` | collapse / expand the output |
| `/` `?` `n` `N` | search cell sources |
| `ZZ` `ZQ` | save and quit / quit without saving |
| `?` | help, `:` command line |

**CELL EDIT mode** — the cursor is a character, and it is vim.

- Motions: `h j k l w W b B e E 0 ^ $ gg G { } % f F t T ; , + -`, counts.
- Operators `d c y > <` with any motion, doubled for linewise (`dd`, `cc`, `yy`, `>>`).
- Text objects: `iw aw i" a" i' a' i( a( i[ a[ i{ a{` (also `ib`, `iB`).
- Edits: `x X s S D C Y p P J ~ r<char> o O i I a A`.
- `u` / `<C-r>` undo and redo, `.` repeats the last change.
- Visual `v` and visual-line `V` with `d y c x p ~ u U > <` and `o` to swap ends.
- `/` `?` `n` `N` search inside the cell.
- Insert mode: auto-indent (including after `:`), `<BS>` unindents, `<C-w>`,
  `<C-u>`, `<Tab>` inserts spaces.
- `<Esc>` in cell NORMAL mode returns to NOTEBOOK mode.

Kernel help while editing: `<C-e>` runs the current cell from anywhere inside
it, `K` shows the kernel's docs for the symbol under the cursor, and `<C-n>`
asks the kernel for completions.

## Command line

```
:w [file]   :wq   :x   :q   :q!   :e file   :new
:run-all    :restart   :interrupt   :clear-all
:kernel [name]   :kernels
:set number | nonumber | tabstop=N
:help
```

`<C-c>` sends an interrupt to the kernel at any time.

## Notes

- Notebooks are read and written as plain nbformat v4 JSON, so a `jnvim` save
  stays diff-friendly and opens fine in JupyterLab.
- `allow_stdin` is off: a cell calling `input()` raises instead of hanging.
- Images and other rich mime types are shown as a `[image/png]` placeholder;
  the data is preserved on save.

## Building a binary

```sh
sh build/build-linux.sh           # -> dist/jnvim  (~18 MB, bundles a kernel)
JNVIM_SLIM=1 sh build/build-linux.sh   # ~10 MB, needs a kernel on the host
```

PyInstaller does not bundle glibc, so the binary requires the build host's
glibc or newer — build on the oldest distro you need to support. The shipped
build is made on Oracle Linux 7.9 (glibc 2.17, `rh-python38`), which gives a
binary needing only `GLIBC_2.14`; it was verified on glibc 2.17 and 2.43.

- `build/ol7-bootstrap.sh` installs the Python 3.8 collection on an EL7 host.
- `build/sync-wsl.ps1` copies the tree into a WSL distro and runs a command there.
- `build/test-binary.sh` runs the pty tests against `dist/jnvim`, both with the
  host kernel and with `-k jnvim-python`.
- `build/test-standalone.sh` hides the build venv to prove the binary works on
  a machine with no Jupyter at all.

Frozen-build details worth knowing: `debugpy` is excluded (it breaks when
frozen, and ipykernel then skips its debugger), a small terminfo database is
bundled because the build host's ncurses only searches its own path, kernel
subprocesses get a cleaned `LD_LIBRARY_PATH`, and kernelspecs that live inside
the bundle are ignored because their interpreter path belongs to the build box.

## Tests

```sh
python3 tests/test_core.py    # vim engine + notebook model, no terminal needed
python3 tests/tui_smoke.py    # drives the real UI through a pty
python3 tests/tui_exec.py     # same, but runs code against a live kernel
```

Set `JNVIM_CMD=./dist/jnvim` to point the pty tests at a built binary.
`tests/setup_wsl_env.sh` creates a throwaway venv with the kernel dependencies.
