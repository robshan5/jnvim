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

```sh
pip install -e .          # pulls in jupyter_client + ipykernel
jnvim notebook.ipynb
```

Or run it straight from the source tree:

```sh
python3 -m jnvim notebook.ipynb
```

Useful flags: `-k/--kernel <name>` to pick a kernel, `--list-kernels`.
The file is created on `:w` if it does not exist yet.

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

## Tests

```sh
python3 tests/test_core.py    # vim engine + notebook model, no terminal needed
python3 tests/tui_smoke.py    # drives the real UI through a pty
python3 tests/tui_exec.py     # same, but runs code against a live kernel
```

`tests/setup_wsl_env.sh` creates a throwaway venv with the kernel dependencies.
