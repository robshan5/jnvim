-- Buffer-local keymaps for notebook buffers.
local cells = require("jnvim.cells")
local config = require("jnvim.config")

local M = {}

function M.attach(bufnr, st)
  local keys = config.options.keymaps
  if not keys.enabled then
    return
  end
  local notebook = require("jnvim.notebook")
  local comment = require("jnvim.percent").comment_char(st.language)

  local function map(mode, lhs, rhs, desc)
    if not lhs or lhs == "" then
      return
    end
    vim.keymap.set(mode, lhs, rhs, { buffer = bufnr, silent = true, desc = "jnvim: " .. desc })
  end

  map("n", keys.run, function()
    notebook.run_cell(bufnr)
  end, "run cell")
  map("n", keys.run_all, function()
    notebook.run_all(bufnr)
  end, "run all cells")
  map("n", keys.run_above, function()
    notebook.run_above(bufnr)
  end, "run cells above")
  map("n", keys.run_line, function()
    notebook.run_text(bufnr, vim.api.nvim_get_current_line())
  end, "run current line")
  map("x", keys.run_line, function()
    vim.cmd('normal! "vy')
    notebook.run_text(bufnr, vim.fn.getreg("v"))
  end, "run selection")
  map("n", keys.next_cell, function()
    cells.goto_cell(bufnr, 1)
  end, "next cell")
  map("n", keys.prev_cell, function()
    cells.goto_cell(bufnr, -1)
  end, "previous cell")
  map("n", keys.cell_below, function()
    cells.insert(bufnr, "below", "code", comment)
  end, "new cell below")
  map("n", keys.cell_above, function()
    cells.insert(bufnr, "above", "code", comment)
  end, "new cell above")
  map("n", keys.cell_markdown, function()
    cells.set_type(bufnr, "markdown", comment)
  end, "cell -> markdown")
  map("n", keys.cell_code, function()
    cells.set_type(bufnr, "code", comment)
  end, "cell -> code")
  map("n", keys.clear, function()
    notebook.clear_cell(bufnr)
  end, "clear cell output")
  map("n", keys.clear_all, function()
    notebook.clear_all(bufnr)
  end, "clear all outputs")
  map("n", keys.interrupt, function()
    require("jnvim").interrupt(bufnr)
  end, "interrupt kernel")
  map("n", keys.restart, function()
    require("jnvim").restart(bufnr)
  end, "restart kernel")
  map("n", keys.toggle_output, function()
    notebook.toggle_output(bufnr)
  end, "toggle output")
  map("n", keys.inspect, function()
    notebook.inspect(bufnr)
  end, "kernel docs")

  if keys.text_object and keys.text_object ~= "" then
    local inner = keys.text_object
    local around = inner:gsub("^i", "a")
    for _, mode in ipairs({ "o", "x" }) do
      map(mode, inner, function()
        cells.select(bufnr, false)
      end, "inside cell")
      map(mode, around, function()
        cells.select(bufnr, true)
      end, "around cell")
    end
  end
end

return M
