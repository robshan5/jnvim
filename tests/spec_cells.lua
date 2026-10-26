-- Cell handling, commands and keymaps; no kernel involved.
--   nvim --headless --clean -u tests/minimal_init.lua -l tests/spec_cells.lua
local cells = require("jnvim.cells")
local failures = {}

local function check(name, got, want)
  if got ~= want then
    table.insert(failures, ("%s\n   got : %s\n   want: %s"):format(name, vim.inspect(got), vim.inspect(want)))
  end
end

local function buffer(lines)
  vim.cmd("enew!")
  local buf = vim.api.nvim_get_current_buf()
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)
  vim.bo[buf].filetype = "python"
  return buf
end

local buf = buffer({
  "# %%",
  "a = 1",
  "",
  "# %% [markdown]",
  "# hi",
  "",
  "# %% [raw]",
  "# verbatim",
})

local list = cells.list(buf)
check("cell count", #list, 3)
check("first type", list[1].cell_type, "code")
check("markdown type", list[2].cell_type, "markdown")
check("raw type", list[3].cell_type, "raw")
check("first body", list[1].first, 2)
check("first body end", list[1].last, 3)
check("marker row", list[2].marker, 4)
check("cell text", cells.text(buf, list[1]), "a = 1")
check("markers detected", cells.is_marker("#%%"), true)
check("non-marker", cells.is_marker("# a comment"), false)
check("js marker", cells.is_marker("// %%"), true)

vim.api.nvim_win_set_cursor(0, { 5, 0 })
local cell, index = cells.at(buf, 5)
check("cell at row 5", index, 2)
check("cell at row 5 type", cell.cell_type, "markdown")

vim.api.nvim_win_set_cursor(0, { 2, 0 })
cells.goto_cell(buf, 1)
check("goto next cell", vim.api.nvim_win_get_cursor(0)[1], 5)
cells.goto_cell(buf, -1)
check("goto previous cell", vim.api.nvim_win_get_cursor(0)[1], 2)

-- text object: inside the cell body only, around includes the marker
cells.select(buf, false)
check("ic start", vim.fn.line("v"), 2)
check("ic end", vim.fn.line("."), 3)
vim.cmd("normal! \27")
vim.api.nvim_win_set_cursor(0, { 2, 0 })
cells.select(buf, true)
check("ac start", vim.fn.line("v"), 1)
vim.cmd("normal! \27")

vim.api.nvim_win_set_cursor(0, { 2, 0 })
cells.insert(buf, "below", "code", "#")
vim.cmd("stopinsert")
check("new marker inserted", vim.api.nvim_buf_get_lines(buf, 3, 4, false)[1], "# %%")
check("cursor in the new cell", vim.api.nvim_win_get_cursor(0)[1], 5)
check("cell count after insert", #cells.list(buf), 4)

cells.set_type(buf, "markdown", "#")
check("type changed", vim.api.nvim_buf_get_lines(buf, 3, 4, false)[1], "# %% [markdown]")
cells.set_type(buf, "code", "#")
check("type changed back", vim.api.nvim_buf_get_lines(buf, 3, 4, false)[1], "# %%")

-- attaching a plain buffer gives it the notebook keymaps and commands
require("jnvim").attach(buf)
check("buffer flagged", vim.b[buf].jnvim, true)
local maps = {}
for _, map in ipairs(vim.api.nvim_buf_get_keymap(buf, "n")) do
  maps[map.lhs] = true
end
check("run keymap", maps[",r"] ~= nil, true)
check("next cell keymap", maps["]c"] ~= nil, true)

check("command exists", vim.fn.exists(":Jnvim"), 2)
local completions = require("jnvim.commands").complete("run", "Jnvim run")
table.sort(completions)
check("completion", vim.tbl_contains(completions, "run-all"), true)
vim.cmd("Jnvim cell-below")
vim.cmd("stopinsert")
check("command inserted a cell", #cells.list(buf), 5)

if #failures > 0 then
  io.stderr:write(("FAILED %d check(s):\n\n%s\n"):format(#failures, table.concat(failures, "\n\n")))
  vim.cmd("cquit 1")
end
print("cell/command test passed")
vim.cmd("qall!")
