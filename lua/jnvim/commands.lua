-- :Jnvim <subcommand> dispatcher.
local cells = require("jnvim.cells")
local notebook = require("jnvim.notebook")

local M = {}

local function current()
  return vim.api.nvim_get_current_buf()
end

local function comment(bufnr)
  local st = notebook.get(bufnr)
  return require("jnvim.percent").comment_char(st and st.language or "python")
end

M.subcommands = {
  run = function()
    require("jnvim").run()
  end,
  ["run-all"] = function()
    require("jnvim").run_all()
  end,
  ["run-above"] = function()
    require("jnvim").run_above()
  end,
  ["run-line"] = function()
    require("jnvim").run_line()
  end,
  start = function(args)
    require("jnvim").start(current(), args[1])
  end,
  stop = function()
    require("jnvim").stop()
  end,
  restart = function()
    require("jnvim").restart()
  end,
  interrupt = function()
    require("jnvim").interrupt()
  end,
  kernels = function()
    require("jnvim").kernels()
  end,
  status = function()
    local st = notebook.get(current())
    if not st then
      vim.notify("[jnvim] not a notebook buffer", vim.log.levels.WARN)
      return
    end
    vim.notify(("[jnvim] %s | kernel %s (%s) | %d cells | %d outputs"):format(
      st.path or "[no file]", st.kernel or "?", st.busy and "busy" or st.kernel_state,
      #cells.list(current()), #st.records), vim.log.levels.INFO)
  end,
  attach = function()
    require("jnvim").attach()
  end,
  open = function(args)
    if not args[1] then
      vim.notify("[jnvim] usage: :Jnvim open <file.ipynb>", vim.log.levels.ERROR)
      return
    end
    vim.cmd.edit(vim.fn.fnameescape(args[1]))
  end,
  save = function(args)
    require("jnvim").save(current(), args[1])
  end,
  clear = function()
    notebook.clear_cell(current())
  end,
  ["clear-all"] = function()
    notebook.clear_all(current())
  end,
  ["toggle-output"] = function()
    notebook.toggle_output(current())
  end,
  ["output-full"] = function()
    notebook.show_full(current())
  end,
  inspect = function()
    notebook.inspect(current())
  end,
  ["cell-below"] = function()
    cells.insert(current(), "below", "code", comment(current()))
  end,
  ["cell-above"] = function()
    cells.insert(current(), "above", "code", comment(current()))
  end,
  markdown = function()
    cells.set_type(current(), "markdown", comment(current()))
  end,
  code = function()
    cells.set_type(current(), "code", comment(current()))
  end,
  raw = function()
    cells.set_type(current(), "raw", comment(current()))
  end,
}

function M.dispatch(opts)
  local args = vim.split(vim.trim(opts.args or ""), "%s+")
  local name = args[1]
  if not name or name == "" then
    name = "run"
  end
  local fn = M.subcommands[name]
  if not fn then
    vim.notify("[jnvim] unknown subcommand: " .. name, vim.log.levels.ERROR)
    return
  end
  require("jnvim")._init()
  fn(vim.list_slice(args, 2))
end

function M.complete(lead, line)
  local args = vim.split(vim.trim(line), "%s+")
  if #args > 2 or (#args == 2 and lead == "") then
    if args[2] == "start" then
      return vim.tbl_filter(function(name)
        return name:find(lead, 1, true) == 1
      end, require("jnvim").kernel_names())
    end
    return {}
  end
  local out = {}
  for name in pairs(M.subcommands) do
    if name:find(lead, 1, true) == 1 then
      table.insert(out, name)
    end
  end
  table.sort(out)
  return out
end

return M
