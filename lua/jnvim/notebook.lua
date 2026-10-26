-- Per-buffer notebook state: load, save, run cells, keep outputs attached.
local bridge = require("jnvim.bridge")
local cells = require("jnvim.cells")
local config = require("jnvim.config")
local output = require("jnvim.output")
local percent = require("jnvim.percent")

local M = {}

---@type table<number, table>
local states = {}
local by_session = {}
local next_token = 0

local function notify(msg, level)
  vim.notify("[jnvim] " .. msg, level or vim.log.levels.INFO)
end

function M.get(bufnr)
  return states[bufnr or vim.api.nvim_get_current_buf()]
end

function M.state(bufnr)
  local st = states[bufnr]
  if not st then
    st = {
      bufnr = bufnr,
      session = tostring(bufnr),
      language = "python",
      kernel = config.options.kernel,
      metadata = {},
      nbformat = 4,
      nbformat_minor = 5,
      records = {},
      tokens = {},
      kernel_state = "stopped",
    }
    states[bufnr] = st
    by_session[st.session] = st
    vim.api.nvim_buf_attach(bufnr, false, {
      on_detach = function()
        M.detach(bufnr)
      end,
    })
  end
  return st
end

function M.detach(bufnr)
  local st = states[bufnr]
  if not st then
    return
  end
  for _, record in ipairs(st.records) do
    require("jnvim.image").clear(record)
  end
  bridge.request("kernel.stop", { session = st.session })
  by_session[st.session] = nil
  states[bufnr] = nil
end

-- ---------------------------------------------------------------- records
local function anchors(cell)
  local marker = cell.marker or cell.first
  return {
    output = math.max(cell.last, marker) - 1,
    prompt = marker - 1,
  }
end

local function record_for_cell(st, cell, create)
  local marker = cell.marker or cell.first
  local first, last = marker - 1, math.max(cell.last, marker) - 1
  for _, record in ipairs(st.records) do
    local row = output.row_of(st.bufnr, record)
    if row and row >= first and row <= last then
      return record
    end
  end
  if not create then
    return nil
  end
  local record = { lines = {}, outputs = {}, cell_id = nil }
  table.insert(st.records, record)
  output.render(st.bufnr, record, anchors(cell))
  return record
end

M.record_for_cell = record_for_cell

local function schedule_render(st, record)
  record.dirty = true
  if record.render_pending then
    return
  end
  record.render_pending = true
  vim.defer_fn(function()
    record.render_pending = false
    if record.dirty and vim.api.nvim_buf_is_valid(st.bufnr) then
      record.dirty = false
      output.render(st.bufnr, record)
    end
  end, 40)
end

-- ------------------------------------------------------------------- load
---@param bufnr number
---@param path string
---@param done fun(ok: boolean)|nil
function M.load(bufnr, path, done)
  bridge.request("notebook.read", { path = path }, function(result, err)
    if err then
      notify("could not read " .. path .. ": " .. err, vim.log.levels.ERROR)
      if done then
        done(false)
      end
      return
    end
    local st = M.state(bufnr)
    st.path = path
    st.language = result.language or "python"
    st.metadata = result.metadata or {}
    st.nbformat = result.nbformat or 4
    st.nbformat_minor = result.nbformat_minor or 5
    st.kernel = result.kernel or config.options.kernel

    local lines = vim.split(result.text or "", "\n", { plain = true })
    vim.bo[bufnr].modifiable = true
    vim.api.nvim_buf_set_lines(bufnr, 0, -1, false, lines)
    vim.bo[bufnr].filetype = st.language
    vim.bo[bufnr].modified = false

    output.clear(bufnr)
    for _, record in ipairs(st.records) do
      require("jnvim.image").clear(record)
    end
    st.records = {}
    local parsed = cells.list(bufnr)
    for index, cell in ipairs(parsed) do
      local info = (result.cells or {})[index]
      if info and (#(info.lines or {}) > 0 or info.execution_count) then
        local record = {
          lines = info.lines or {},
          outputs = info.outputs or {},
          count = info.execution_count,
          cell_id = info.id,
        }
        table.insert(st.records, record)
        output.render(bufnr, record, anchors(cell))
      end
    end
    M.setup_buffer(bufnr)
    if config.options.auto_start then
      M.ensure_kernel(bufnr)
    end
    if done then
      done(true)
    end
  end)
end

-- ------------------------------------------------------------------- save
function M.save(bufnr, path, done)
  local st = M.state(bufnr)
  path = path or st.path
  if not path then
    notify("this buffer is not backed by a notebook", vim.log.levels.ERROR)
    return
  end
  local text = table.concat(vim.api.nvim_buf_get_lines(bufnr, 0, -1, false), "\n")
  local extras = {}
  for index, cell in ipairs(cells.list(bufnr)) do
    local record = record_for_cell(st, cell, false)
    if record and config.options.auto_save_outputs then
      extras[index] = {
        outputs = record.outputs,
        execution_count = record.count,
        id = record.cell_id,
      }
    else
      extras[index] = vim.empty_dict()
    end
  end
  bridge.request("notebook.write", {
    path = path,
    text = text,
    language = st.language,
    kernel = st.kernel,
    metadata = st.metadata,
    nbformat = st.nbformat,
    nbformat_minor = st.nbformat_minor,
    cells = extras,
  }, function(result, err)
    if err then
      notify("write failed: " .. err, vim.log.levels.ERROR)
      return
    end
    st.path = path
    vim.bo[bufnr].modified = false
    notify(('"%s" %d cells written'):format(path, result.cells))
    if done then
      done(true)
    end
  end)
end

-- ----------------------------------------------------------------- kernel
function M.ensure_kernel(bufnr)
  local st = M.state(bufnr)
  if st.kernel_state == "ready" or st.kernel_state == "starting" then
    return
  end
  st.kernel_state = "starting"
  bridge.request("kernel.start", { session = st.session, kernel = st.kernel })
end

function M.run_cell(bufnr, cell)
  local st = M.state(bufnr)
  cell = cell or cells.at(bufnr, vim.api.nvim_win_get_cursor(0)[1])
  if not cell then
    return
  end
  if cell.cell_type ~= "code" then
    return
  end
  local code = cells.text(bufnr, cell)
  if code:match("^%s*$") then
    return
  end
  M.ensure_kernel(bufnr)

  local record = record_for_cell(st, cell, true)
  record.lines = {}
  record.outputs = {}
  record.count = nil
  record.status = nil
  record.elapsed = nil
  record.running = true
  record.started = vim.uv and vim.uv.hrtime() or vim.loop.hrtime()
  output.render(bufnr, record, anchors(cell))

  next_token = next_token + 1
  local token = next_token
  st.tokens[token] = record
  bridge.request("kernel.execute", {
    session = st.session,
    kernel = st.kernel,
    code = code,
    token = token,
  }, function(result, err)
    if err then
      record.running = false
      output.render(bufnr, record)
      notify("execute failed: " .. err, vim.log.levels.ERROR)
    elseif result and result.queued == false then
      record.running = false
      record.lines = { { "kernel is " .. (result.state or "not running"), "err" } }
      output.render(bufnr, record)
    end
  end)
end

function M.run_range(bufnr, from, to)
  local list = cells.list(bufnr)
  for index = from or 1, math.min(to or #list, #list) do
    M.run_cell(bufnr, list[index])
  end
end

function M.run_all(bufnr)
  M.run_range(bufnr, 1, nil)
end

function M.run_above(bufnr)
  local _, index = cells.at(bufnr, vim.api.nvim_win_get_cursor(0)[1])
  M.run_range(bufnr, 1, (index or 1) - 1)
end

--- Run arbitrary text (a line or a visual selection) without touching outputs.
function M.run_text(bufnr, code)
  if not code or code:match("^%s*$") then
    return
  end
  local st = M.state(bufnr)
  M.ensure_kernel(bufnr)
  local cell = cells.at(bufnr, vim.api.nvim_win_get_cursor(0)[1])
  local record = record_for_cell(st, cell, true)
  record.lines = {}
  record.outputs = {}
  record.running = true
  output.render(bufnr, record, anchors(cell))
  next_token = next_token + 1
  st.tokens[next_token] = record
  bridge.request("kernel.execute", {
    session = st.session,
    kernel = st.kernel,
    code = code,
    token = next_token,
  })
end

function M.clear_cell(bufnr)
  local st = M.state(bufnr)
  local cell = cells.at(bufnr, vim.api.nvim_win_get_cursor(0)[1])
  local record = record_for_cell(st, cell, false)
  if record then
    output.erase(bufnr, record)
    for index, item in ipairs(st.records) do
      if item == record then
        table.remove(st.records, index)
        break
      end
    end
    vim.bo[bufnr].modified = true
  end
end

function M.clear_all(bufnr)
  local st = M.state(bufnr)
  for _, record in ipairs(st.records) do
    require("jnvim.image").clear(record)
  end
  output.clear(bufnr)
  st.records = {}
  vim.bo[bufnr].modified = true
end

function M.toggle_output(bufnr)
  local st = M.state(bufnr)
  local cell = cells.at(bufnr, vim.api.nvim_win_get_cursor(0)[1])
  local record = record_for_cell(st, cell, false)
  if record then
    record.hidden = not record.hidden
    output.render(bufnr, record)
  end
end

function M.show_full(bufnr)
  local st = M.state(bufnr)
  local cell = cells.at(bufnr, vim.api.nvim_win_get_cursor(0)[1])
  local record = record_for_cell(st, cell, false)
  if record then
    output.show_full(record, "jnvim://output")
  end
end

function M.open_image(bufnr)
  local st = M.state(bufnr)
  local cell = cells.at(bufnr, vim.api.nvim_win_get_cursor(0)[1])
  local record = record_for_cell(st, cell, false)
  if record then
    require("jnvim.image").open_external(record)
  end
end

function M.inspect(bufnr)
  local st = M.state(bufnr)
  local cell = cells.at(bufnr, vim.api.nvim_win_get_cursor(0)[1])
  local code = cells.text(bufnr, cell)
  local cursor = vim.api.nvim_win_get_cursor(0)
  local offset = 0
  for row = cell.first, cursor[1] - 1 do
    offset = offset + #(vim.api.nvim_buf_get_lines(bufnr, row - 1, row, false)[1] or "") + 1
  end
  offset = offset + cursor[2]
  bridge.request("kernel.inspect", { session = st.session, code = code, pos = offset },
    function(result, err)
      if err or not result or result.text == "" then
        notify("no documentation found")
        return
      end
      local lines = vim.split(result.text, "\n", { plain = true })
      vim.lsp.util.open_floating_preview(lines, "markdown", {
        border = "rounded",
        max_width = 100,
        max_height = 25,
      })
    end)
end

--- omnifunc-compatible completion backed by the kernel.
function M.omnifunc(findstart, base)
  local bufnr = vim.api.nvim_get_current_buf()
  local st = states[bufnr]
  if not st then
    return findstart == 1 and -3 or {}
  end
  local line = vim.api.nvim_get_current_line()
  local col = vim.api.nvim_win_get_cursor(0)[2]
  if findstart == 1 then
    local start = col
    while start > 0 and line:sub(start, start):match("[%w_%.]") do
      start = start - 1
    end
    return start
  end
  local result = nil
  bridge.request("kernel.complete", { session = st.session, code = line, pos = col },
    function(res)
      result = res or { matches = {} }
    end)
  vim.wait(2000, function()
    return result ~= nil
  end, 20)
  return (result or {}).matches or {}
end

-- ----------------------------------------------------------------- events
local function on_event(frame)
  local st = by_session[tostring(frame.session)]
  if not st or not vim.api.nvim_buf_is_valid(st.bufnr) then
    return
  end
  local event = frame.event
  if event == "kernel" then
    st.kernel_state = frame.state == "ready" and "ready" or "dead"
    if frame.state == "dead" then
      notify("kernel: " .. (frame.message or "died"), vim.log.levels.WARN)
    end
    return
  end
  if event == "status" then
    st.busy = frame.state == "busy"
    return
  end
  local record = frame.token and st.tokens[frame.token]
  if not record then
    return
  end
  if event == "input" then
    record.count = frame.count
    schedule_render(st, record)
  elseif event == "output" then
    table.insert(record.outputs, frame.output)
    for _, line in ipairs(frame.lines or {}) do
      table.insert(record.lines, line)
    end
    vim.bo[st.bufnr].modified = true
    schedule_render(st, record)
  elseif event == "clear" then
    record.outputs = {}
    record.lines = {}
    schedule_render(st, record)
  elseif event == "done" then
    record.running = false
    record.status = frame.status
    record.count = frame.count or record.count
    if record.started then
      local now = vim.uv and vim.uv.hrtime() or vim.loop.hrtime()
      record.elapsed = (now - record.started) / 1e9
    end
    st.tokens[frame.token] = nil
    record.dirty = false
    output.render(st.bufnr, record)
  end
end

function M.init_events()
  for _, event in ipairs({ "kernel", "status", "input", "output", "clear", "done" }) do
    bridge.on(event, on_event)
  end
  bridge.on("error", function(frame)
    notify(frame.message or "bridge error", vim.log.levels.ERROR)
  end)
end

-- ----------------------------------------------------------------- buffer
function M.setup_buffer(bufnr)
  local st = M.state(bufnr)
  vim.b[bufnr].jnvim = true
  vim.bo[bufnr].omnifunc = "v:lua.require'jnvim.notebook'.omnifunc"
  require("jnvim.keymaps").attach(bufnr, st)
end

function M.comment_char(bufnr)
  return percent.comment_char(M.state(bufnr).language)
end

function M.status(bufnr)
  local st = states[bufnr or vim.api.nvim_get_current_buf()]
  if not st then
    return ""
  end
  local state = st.busy and "busy" or st.kernel_state
  return ("%s:%s"):format(st.kernel or "?", state)
end

return M
