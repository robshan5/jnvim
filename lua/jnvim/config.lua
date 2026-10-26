local M = {}

---@class JnvimConfig
M.defaults = {
  -- python interpreter that has jupyter_client (and ipykernel) installed
  python = nil, -- nil -> first of g:python3_host_prog, "python3", "python"
  -- kernel to use when the notebook does not name one
  kernel = "python3",
  -- start a kernel as soon as a notebook is opened
  auto_start = true,
  -- write the .ipynb on :w (BufWriteCmd); false leaves the file alone
  auto_save_outputs = true,

  output = {
    enabled = true,
    max_lines = 24, -- per cell; the rest is folded into a "N more lines" note
    prefix = "  ",
    show_prompt = true, -- virtual "In [3]  0.42s" next to the cell marker
    running_text = "running...",
  },

  keymaps = {
    enabled = true,
    run = "<localleader>r", -- run the cell under the cursor
    run_all = "<localleader>R", -- run every cell
    run_above = "<localleader>a", -- run all cells above the cursor
    run_line = "<localleader>l", -- run the current line / visual selection
    next_cell = "]c",
    prev_cell = "[c",
    cell_below = "<localleader>o",
    cell_above = "<localleader>O",
    cell_markdown = "<localleader>m",
    cell_code = "<localleader>y",
    clear = "<localleader>c",
    clear_all = "<localleader>C",
    interrupt = "<localleader>i",
    restart = "<localleader>x",
    inspect = "K",
    toggle_output = "<localleader>t",
    text_object = "ic", -- also gives "ac" (cell with its marker)
  },
}

---@type JnvimConfig
M.options = vim.deepcopy(M.defaults)

function M.setup(opts)
  M.options = vim.tbl_deep_extend("force", vim.deepcopy(M.defaults), opts or {})
  return M.options
end

function M.python()
  if M.options.python then
    return M.options.python
  end
  local candidates = { vim.g.python3_host_prog, "python3", "python" }
  for _, exe in ipairs(candidates) do
    if exe and vim.fn.executable(exe) == 1 then
      return exe
    end
  end
  return "python3"
end

return M
