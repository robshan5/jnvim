-- Cell outputs rendered as virtual lines; nothing is written into the buffer.
local config = require("jnvim.config")

local M = {}

M.ns = vim.api.nvim_create_namespace("jnvim-output")
M.ns_prompt = vim.api.nvim_create_namespace("jnvim-prompt")

local HL = {
  out = "JnvimOutput",
  stream = "JnvimOutput",
  err = "JnvimError",
}

function M.setup_highlights()
  local defaults = {
    JnvimOutput = { link = "Comment", default = true },
    JnvimError = { link = "DiagnosticError", default = true },
    JnvimPrompt = { link = "Special", default = true },
    JnvimRunning = { link = "DiagnosticWarn", default = true },
    JnvimMore = { link = "NonText", default = true },
  }
  for name, opts in pairs(defaults) do
    vim.api.nvim_set_hl(0, name, opts)
  end
end

local function virt_lines(record)
  local opts = config.options.output
  local lines = {}
  local total = #record.lines
  local shown = math.min(total, opts.max_lines)
  for index = 1, shown do
    local entry = record.lines[index]
    local text = (entry[1] or ""):gsub("\r", "")
    table.insert(lines, { { opts.prefix .. text, HL[entry[2]] or HL.out } })
  end
  if total > shown then
    table.insert(lines, {
      { ("%s... %d more lines (:Jnvim output-full)"):format(opts.prefix, total - shown), "JnvimMore" },
    })
  end
  return lines
end

local function prompt_text(record)
  local opts = config.options.output
  if not opts.show_prompt then
    return nil
  end
  if record.running then
    return { { "  " .. opts.running_text, "JnvimRunning" } }
  end
  if not record.count and #record.lines == 0 then
    return nil
  end
  local label = record.count and ("In [%d]"):format(record.count) or "In [ ]"
  if record.elapsed then
    label = ("%s  %.2fs"):format(label, record.elapsed)
  end
  if record.status == "error" then
    label = label .. "  error"
  end
  return { { "  " .. label, record.status == "error" and "JnvimError" or "JnvimPrompt" } }
end

local function set_mark(bufnr, ns, id, row, opts)
  opts = vim.tbl_extend("force", opts, { id = id })
  local line_count = vim.api.nvim_buf_line_count(bufnr)
  row = math.max(0, math.min(row, line_count - 1))
  local ok, mark = pcall(vim.api.nvim_buf_set_extmark, bufnr, ns, row, 0, opts)
  if ok then
    return mark
  end
  return nil
end

--- Draw (or redraw) one record.
---@param rows table|nil { output = row0, prompt = row0 } to (re)anchor the marks
function M.render(bufnr, record, rows)
  if not vim.api.nvim_buf_is_valid(bufnr) then
    return
  end
  local enabled = config.options.output.enabled and not record.hidden

  local out_row = rows and rows.output
  if not out_row and record.out_mark then
    local pos = vim.api.nvim_buf_get_extmark_by_id(bufnr, M.ns, record.out_mark, {})
    out_row = pos and pos[1]
  end
  out_row = out_row or record.out_row
  if out_row then
    record.out_row = out_row
    if enabled and #record.lines > 0 then
      record.out_mark = set_mark(bufnr, M.ns, record.out_mark, out_row, {
        virt_lines = virt_lines(record),
        virt_lines_above = false,
      })
    elseif record.out_mark then
      pcall(vim.api.nvim_buf_del_extmark, bufnr, M.ns, record.out_mark)
      record.out_mark = nil
    end
  end

  local prompt_row = rows and rows.prompt
  if not prompt_row and record.prompt_mark then
    local pos = vim.api.nvim_buf_get_extmark_by_id(bufnr, M.ns_prompt, record.prompt_mark, {})
    prompt_row = pos and pos[1]
  end
  prompt_row = prompt_row or record.prompt_row
  if prompt_row then
    record.prompt_row = prompt_row
    local text = prompt_text(record)
    if text then
      record.prompt_mark = set_mark(bufnr, M.ns_prompt, record.prompt_mark, prompt_row, {
        virt_text = text,
        virt_text_pos = "eol",
        hl_mode = "combine",
      })
    elseif record.prompt_mark then
      pcall(vim.api.nvim_buf_del_extmark, bufnr, M.ns_prompt, record.prompt_mark)
      record.prompt_mark = nil
    end
  end
end

function M.row_of(bufnr, record)
  if record.out_mark then
    local pos = vim.api.nvim_buf_get_extmark_by_id(bufnr, M.ns, record.out_mark, {})
    if pos and pos[1] then
      return pos[1]
    end
  end
  if record.prompt_mark then
    local pos = vim.api.nvim_buf_get_extmark_by_id(bufnr, M.ns_prompt, record.prompt_mark, {})
    if pos and pos[1] then
      return pos[1]
    end
  end
  return record.out_row or record.prompt_row
end

function M.erase(bufnr, record)
  if record.out_mark then
    pcall(vim.api.nvim_buf_del_extmark, bufnr, M.ns, record.out_mark)
  end
  if record.prompt_mark then
    pcall(vim.api.nvim_buf_del_extmark, bufnr, M.ns_prompt, record.prompt_mark)
  end
  record.out_mark, record.prompt_mark = nil, nil
  record.out_row, record.prompt_row = nil, nil
end

function M.clear(bufnr)
  pcall(vim.api.nvim_buf_clear_namespace, bufnr, M.ns, 0, -1)
  pcall(vim.api.nvim_buf_clear_namespace, bufnr, M.ns_prompt, 0, -1)
end

--- Open the full output of a record in a scratch split.
function M.show_full(record, title)
  local lines = {}
  for _, entry in ipairs(record.lines) do
    table.insert(lines, entry[1])
  end
  if #lines == 0 then
    vim.notify("[jnvim] no output for this cell", vim.log.levels.INFO)
    return
  end
  vim.cmd("botright new")
  local buf = vim.api.nvim_get_current_buf()
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)
  vim.bo[buf].buftype = "nofile"
  vim.bo[buf].bufhidden = "wipe"
  vim.bo[buf].modifiable = false
  vim.api.nvim_buf_set_name(buf, title or "jnvim://output")
end

return M
