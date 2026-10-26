-- jnvim.nvim: run Jupyter notebooks inside Neovim.
local bridge = require("jnvim.bridge")
local config = require("jnvim.config")
local notebook = require("jnvim.notebook")
local output = require("jnvim.output")

local M = {}

local initialised = false

function M._init()
  if initialised then
    return
  end
  initialised = true
  output.setup_highlights()
  notebook.init_events()
end

---@param opts table|nil
function M.setup(opts)
  config.setup(opts)
  M._init()
end

local function buf(bufnr)
  return bufnr or vim.api.nvim_get_current_buf()
end

--- Load a .ipynb into `bufnr` (used by the BufReadCmd autocmd).
function M.open(bufnr, path)
  M._init()
  bufnr = buf(bufnr)
  path = path or vim.api.nvim_buf_get_name(bufnr)
  notebook.load(bufnr, path)
end

--- Write `bufnr` back to its .ipynb (used by the BufWriteCmd autocmd).
function M.save(bufnr, path)
  M._init()
  notebook.save(buf(bufnr), path)
end

--- Treat any percent-format buffer as a notebook (no .ipynb behind it).
function M.attach(bufnr)
  M._init()
  bufnr = buf(bufnr)
  local st = notebook.state(bufnr)
  st.language = vim.bo[bufnr].filetype ~= "" and vim.bo[bufnr].filetype or "python"
  notebook.setup_buffer(bufnr)
  if config.options.auto_start then
    notebook.ensure_kernel(bufnr)
  end
  vim.notify("[jnvim] attached (" .. st.language .. ")", vim.log.levels.INFO)
end

function M.run(bufnr)
  M._init()
  notebook.run_cell(buf(bufnr))
end

function M.run_all(bufnr)
  M._init()
  notebook.run_all(buf(bufnr))
end

function M.run_above(bufnr)
  M._init()
  notebook.run_above(buf(bufnr))
end

function M.run_line(bufnr)
  M._init()
  bufnr = buf(bufnr)
  notebook.run_text(bufnr, vim.api.nvim_get_current_line())
end

function M.start(bufnr, kernel)
  M._init()
  bufnr = buf(bufnr)
  local st = notebook.state(bufnr)
  if kernel and kernel ~= "" then
    st.kernel = kernel
    st.kernel_state = "stopped"
    bridge.request("kernel.stop", { session = st.session })
  end
  notebook.ensure_kernel(bufnr)
end

function M.stop(bufnr)
  bufnr = buf(bufnr)
  local st = notebook.get(bufnr)
  if st then
    st.kernel_state = "stopped"
    bridge.request("kernel.stop", { session = st.session })
  end
end

function M.restart(bufnr)
  bufnr = buf(bufnr)
  local st = notebook.get(bufnr)
  if not st then
    return
  end
  bridge.request("kernel.restart", { session = st.session })
  vim.notify("[jnvim] restarting kernel", vim.log.levels.INFO)
end

function M.interrupt(bufnr)
  bufnr = buf(bufnr)
  local st = notebook.get(bufnr)
  if st then
    bridge.request("kernel.interrupt", { session = st.session })
  end
end

function M.kernels(cb)
  M._init()
  bridge.request("kernel.list", {}, function(result, err)
    if err then
      vim.notify("[jnvim] " .. err, vim.log.levels.ERROR)
      return
    end
    M._kernel_names = {}
    for _, spec in ipairs(result.kernels or {}) do
      table.insert(M._kernel_names, spec.name)
    end
    if cb then
      cb(result.kernels or {})
      return
    end
    local lines = {}
    for _, spec in ipairs(result.kernels or {}) do
      table.insert(lines, ("%-22s %s"):format(spec.name, spec.display_name))
    end
    vim.notify("[jnvim] kernels:\n" .. table.concat(lines, "\n"), vim.log.levels.INFO)
  end)
end

--- Kernel names from the last `kernel.list`; refreshes in the background.
function M.kernel_names()
  if not M._kernel_names then
    M.kernels(function() end)
    return {}
  end
  return M._kernel_names
end

--- `vim.o.statusline` helper: "python3:idle".
function M.status(bufnr)
  return notebook.status(buf(bufnr))
end

M.notebook = notebook
M.bridge = bridge
M.config = config

return M
