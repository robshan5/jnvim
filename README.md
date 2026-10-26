# jnvim.nvim

Run Jupyter notebooks inside Neovim. `.ipynb` files open as ordinary buffers in
jupytext *percent* format, cells run against a real Jupyter kernel, and output
appears as virtual text under each cell — the buffer text itself is never
touched.

Editing is just Neovim: your motions, operators, treesitter, LSP, completion
and colour scheme all keep working, because a notebook is only a python buffer
with `# %%` markers.

```python
# %%                                     In [1]  0.41s
import numpy as np
np.arange(5).sum()
  10

# %% [markdown]
# ## Results
# the sum above is 10

# %%                                     running...
import time; time.sleep(2)
```

## Requirements

- Neovim 0.9+
- a Python with `jupyter_client` (and `ipykernel` for a Python kernel):
  `pip install jupyter_client ipykernel`

`:checkhealth jnvim` verifies all of it.

## Install

lazy.nvim:

```lua
{ "jnvim.nvim", ft = "ipynb", opts = {} }
```

packer.nvim:

```lua
use({ "jnvim.nvim", config = function() require("jnvim").setup({}) end })
```

`setup()` is optional — it only overrides defaults. If your Python lives in a
venv, point at it:

```lua
require("jnvim").setup({ python = "~/.venvs/jupyter/bin/python" })
```

## Use it

Open any `.ipynb` and run cells.

| key | action |
| --- | --- |
| `<localleader>r` | run the cell under the cursor |
| `<localleader>R` / `<localleader>a` | run every cell / every cell above |
| `<localleader>l` | run the current line (visual: the selection) |
| `]c` / `[c` | next / previous cell |
| `<localleader>o` / `<localleader>O` | new cell below / above |
| `<localleader>m` / `<localleader>y` | cell → markdown / code |
| `<localleader>c` / `<localleader>C` | clear this output / all outputs |
| `<localleader>i` / `<localleader>x` | interrupt / restart the kernel |
| `<localleader>t` | hide or show this cell's output |
| `K` | kernel docs for the symbol under the cursor |
| `ic` / `ac` | text object: cell body / cell with its marker |

Everything is also available as `:Jnvim <subcommand>` with completion:
`run`, `run-all`, `run-above`, `run-line`, `start [kernel]`, `stop`, `restart`,
`interrupt`, `kernels`, `status`, `attach`, `open`, `save`, `clear`,
`clear-all`, `toggle-output`, `output-full`, `inspect`, `cell-below`,
`cell-above`, `markdown`, `code`, `raw`.

`:w` writes the `.ipynb` back, keeping cell ids, execution counts and outputs.
Outputs are anchored with extmarks, so they follow their cell as you edit.

Already have a `.py` in percent format? `:Jnvim attach` gives it the same
mappings and a kernel without any notebook file behind it.

`require("jnvim").status()` returns `"python3:idle"` for your statusline.

See `:help jnvim` for the full option list.

## How it works

```
   Neovim (lua/jnvim)                  python/jnvim                 kernel
   buffer, cells, extmarks  <--JSON-->   bridge     <--ZMQ-->    ipykernel
```

The Lua half owns the buffer, the cell boundaries and the virtual text. A small
Python process is started on demand and speaks one JSON object per line over
stdio; one kernel is started per notebook buffer. The bridge writes nothing but
protocol frames to stdout and sends the kernel's own stdout/stderr to
`/dev/null`, so a chatty kernel can never corrupt the channel.

## Tests

```sh
JNVIM_PYTHON=/path/to/python sh tests/run.sh
```

- `tests/test_python.py` — percent round-trips and `.ipynb` reading/writing
- `tests/spec_cells.lua` — cells, commands, keymaps and text objects (no kernel)
- `tests/spec.lua` — headless Neovim: open a notebook, run cells against a live
  kernel, check the virtual output, save and re-read the file

`scripts/sync-wsl.ps1` copies the plugin into a WSL distro and runs a command
there, which is how the suite is run from Windows.
