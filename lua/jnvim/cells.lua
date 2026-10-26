-- Cell boundaries in a percent-format buffer.
local M = {}

local MARKERS = {
  "^%s*#%s*%%%%", -- # %%
  "^%s*//%s*%%%%", -- // %%
  "^%s*%-%-%s*%%%%", -- -- %%
  "^%s*%%%s*%%%%", -- % %%
}

---@return boolean
function M.is_marker(line)
  for _, pattern in ipairs(MARKERS) do
    if line:match(pattern) then
      return true
    end
  end
  return false
end

local function marker_type(line)
  local tag = line:match("%[(%a+)%]")
  if not tag then
    return "code"
  end
  tag = tag:lower()
  if tag == "md" then
    return "markdown"
  end
  if tag == "markdown" or tag == "raw" then
    return tag
  end
  return "code"
end

--- All cells of a buffer.
--- Rows are 1-based; `first`/`last` describe the body and may be empty
--- (`last < first`) when a cell only has its marker line.
---@return table[]
function M.list(bufnr)
  local lines = vim.api.nvim_buf_get_lines(bufnr, 0, -1, false)
  local cells = {}
  local current = nil
  for row, line in ipairs(lines) do
    if M.is_marker(line) then
      if current then
        current.last = row - 1
        table.insert(cells, current)
      end
      current = { marker = row, first = row + 1, cell_type = marker_type(line) }
    elseif not current then
      current = { marker = nil, first = row, cell_type = "code" }
    end
  end
  if current then
    current.last = #lines
    table.insert(cells, current)
  end
  if #cells == 0 then
    cells = { { marker = nil, first = 1, last = 0, cell_type = "code" } }
  end
  for index, cell in ipairs(cells) do
    cell.index = index
    cell.anchor = math.max(cell.marker or cell.first, cell.last)
  end
  return cells
end

---@return table|nil cell, number|nil index
function M.at(bufnr, row)
  row = row or vim.api.nvim_win_get_cursor(0)[1]
  local cells = M.list(bufnr)
  for index, cell in ipairs(cells) do
    local start = cell.marker or cell.first
    if row >= start and row <= math.max(cell.last, start) then
      return cell, index
    end
  end
  return cells[#cells], #cells
end

---@return string
function M.text(bufnr, cell)
  if cell.last < cell.first then
    return ""
  end
  local lines = vim.api.nvim_buf_get_lines(bufnr, cell.first - 1, cell.last, false)
  while #lines > 0 and lines[#lines]:match("^%s*$") do
    table.remove(lines)
  end
  return table.concat(lines, "\n")
end

--- Jump to the next/previous cell marker.
function M.goto_cell(bufnr, delta)
  local cells = M.list(bufnr)
  local _, index = M.at(bufnr, vim.api.nvim_win_get_cursor(0)[1])
  local target = cells[math.max(1, math.min(#cells, (index or 1) + delta))]
  if not target then
    return
  end
  local row = target.marker and math.min(target.marker + 1, vim.api.nvim_buf_line_count(bufnr))
    or target.first
  vim.api.nvim_win_set_cursor(0, { math.max(1, row), 0 })
end

--- Insert a new cell above or below the current one and start inserting.
function M.insert(bufnr, where, cell_type, comment)
  comment = comment or "#"
  local cells = M.list(bufnr)
  local _, index = M.at(bufnr, vim.api.nvim_win_get_cursor(0)[1])
  local cell = cells[index or 1]
  local tag = cell_type == "markdown" and " [markdown]" or (cell_type == "raw" and " [raw]" or "")
  local marker = ("%s %%%%%s"):format(comment, tag)
  local at
  if where == "above" then
    at = (cell.marker or cell.first) - 1
  else
    at = math.max(cell.last, cell.marker or cell.first)
  end
  vim.api.nvim_buf_set_lines(bufnr, at, at, false, { marker, "", "" })
  vim.api.nvim_win_set_cursor(0, { at + 2, 0 })
  vim.cmd("startinsert")
end

--- Change the type of the cell under the cursor.
function M.set_type(bufnr, cell_type, comment)
  comment = comment or "#"
  local cell = M.at(bufnr, vim.api.nvim_win_get_cursor(0)[1])
  if not cell then
    return
  end
  local tag = cell_type == "markdown" and " [markdown]" or (cell_type == "raw" and " [raw]" or "")
  local marker = ("%s %%%%%s"):format(comment, tag)
  if cell.marker then
    vim.api.nvim_buf_set_lines(bufnr, cell.marker - 1, cell.marker, false, { marker })
  else
    vim.api.nvim_buf_set_lines(bufnr, 0, 0, false, { marker })
  end
end

--- Visually select the cell under the cursor (`ic` / `ac`).
function M.select(bufnr, around)
  local cell = M.at(bufnr, vim.api.nvim_win_get_cursor(0)[1])
  if not cell then
    return
  end
  local first = around and (cell.marker or cell.first) or cell.first
  local last = math.max(cell.last, first)
  vim.api.nvim_win_set_cursor(0, { first, 0 })
  vim.cmd("normal! V")
  vim.api.nvim_win_set_cursor(0, { last, 0 })
end

return M
