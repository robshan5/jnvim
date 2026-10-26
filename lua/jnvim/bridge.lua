-- Job control + JSON-line RPC with python/jnvim.
local config = require("jnvim.config")

local M = {}

local state = {
  job = nil,
  next_id = 0,
  pending = {},
  handlers = {},
  partial = "",
  stderr = {},
}

local function root()
  local source = debug.getinfo(1, "S").source:sub(2)
  -- lua/jnvim/bridge.lua -> plugin root
  return vim.fn.fnamemodify(source, ":h:h:h")
end

M.root = root

local function notify(msg, level)
  vim.schedule(function()
    vim.notify("[jnvim] " .. msg, level or vim.log.levels.ERROR)
  end)
end

local function dispatch(frame)
  if frame.event then
    local list = state.handlers[frame.event]
    if list then
      for _, fn in ipairs(list) do
        pcall(fn, frame)
      end
    end
    return
  end
  local cb = state.pending[frame.id]
  state.pending[frame.id] = nil
  if cb then
    if frame.ok then
      pcall(cb, frame.result, nil)
    else
      pcall(cb, nil, frame.error or "bridge error")
    end
  elseif not frame.ok then
    notify(frame.error or "bridge error")
  end
end

local function on_stdout(_, data)
  if not data then
    return
  end
  for index, chunk in ipairs(data) do
    if index > 1 then
      local line = state.partial
      state.partial = ""
      if line ~= "" then
        local ok, frame = pcall(vim.json.decode, line)
        if ok and type(frame) == "table" then
          dispatch(frame)
        end
      end
    end
    state.partial = state.partial .. chunk
  end
end

local function on_stderr(_, data)
  if not data then
    return
  end
  for _, line in ipairs(data) do
    if line ~= "" then
      table.insert(state.stderr, line)
      if #state.stderr > 50 then
        table.remove(state.stderr, 1)
      end
    end
  end
end

local function on_exit(_, code)
  state.job = nil
  for id, cb in pairs(state.pending) do
    state.pending[id] = nil
    pcall(cb, nil, "bridge exited")
  end
  if code ~= 0 then
    local tail = table.concat(vim.list_slice(state.stderr, math.max(1, #state.stderr - 5)), "\n")
    notify(("python bridge exited (code %d)\n%s"):format(code, tail))
  end
end

function M.running()
  return state.job ~= nil
end

function M.start()
  if state.job then
    return true
  end
  local python = config.python()
  if vim.fn.executable(python) ~= 1 then
    notify(("python not found: %s (set require('jnvim').setup{ python = ... })"):format(python))
    return false
  end
  state.stderr = {}
  -- an explicit sys.path keeps a stray jnvim.py in the cwd from shadowing us;
  -- the cwd itself stays the editor's so kernels see the user's files
  local boot = ([[import sys; sys.path.insert(0, %q); from jnvim.__main__ import main; sys.exit(main())]])
    :format(root() .. "/python")
  local job = vim.fn.jobstart({ python, "-u", "-c", boot }, {
    cwd = vim.fn.getcwd(),
    env = { PYTHONDONTWRITEBYTECODE = "1" },
    stdout_buffered = false,
    on_stdout = on_stdout,
    on_stderr = on_stderr,
    on_exit = on_exit,
  })
  if job <= 0 then
    notify("could not start the python bridge")
    return false
  end
  state.job = job
  return true
end

function M.stop()
  if state.job then
    M.request("shutdown", {})
    vim.fn.jobstop(state.job)
    state.job = nil
  end
end

---@param method string
---@param params table|nil
---@param cb fun(result: table|nil, err: string|nil)|nil
function M.request(method, params, cb)
  if not M.start() then
    if cb then
      cb(nil, "bridge unavailable")
    end
    return
  end
  state.next_id = state.next_id + 1
  local id = state.next_id
  if cb then
    state.pending[id] = cb
  end
  local line = vim.json.encode({ id = id, method = method, params = params or vim.empty_dict() })
  vim.fn.chansend(state.job, line .. "\n")
end

---@param event string
---@param fn fun(frame: table)
function M.on(event, fn)
  state.handlers[event] = state.handlers[event] or {}
  table.insert(state.handlers[event], fn)
end

function M.stderr_tail()
  return state.stderr
end

return M
