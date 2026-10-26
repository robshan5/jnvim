-- Headless integration test:  nvim --headless -u tests/minimal_init.lua -l tests/spec.lua
-- Opens a notebook, checks the buffer, runs a cell against a real kernel and
-- verifies the saved .ipynb.
local failures = {}

local function check(name, got, want)
  if got ~= want then
    table.insert(failures, ("%s\n   got : %s\n   want: %s"):format(name, vim.inspect(got), vim.inspect(want)))
  end
end

local function wait(desc, fn, ms)
  if not vim.wait(ms or 20000, fn, 50) then
    table.insert(failures, "timeout waiting for " .. desc)
    return false
  end
  return true
end

local root = vim.fn.fnamemodify(debug.getinfo(1, "S").source:sub(2), ":h:h")
local tmp = vim.fn.tempname()
vim.fn.mkdir(tmp, "p")
local path = tmp .. "/demo.ipynb"

vim.fn.writefile({ vim.json.encode({
  cells = {
    { cell_type = "code", source = { "a = 6 * 7" }, outputs = {}, execution_count = vim.NIL, metadata = vim.empty_dict() },
    { cell_type = "markdown", source = { "# heading" }, metadata = vim.empty_dict() },
    { cell_type = "code", source = { 'print("hi from kernel")\n', "a" }, outputs = {}, execution_count = vim.NIL, metadata = vim.empty_dict() },
  },
  metadata = { kernelspec = { name = "python3", display_name = "Python 3", language = "python" } },
  nbformat = 4,
  nbformat_minor = 5,
}) }, path)

-- minimal_init.lua already called setup() with JNVIM_PYTHON
vim.cmd.edit(vim.fn.fnameescape(path))
local buf = vim.api.nvim_get_current_buf()

wait("the notebook to load", function()
  return (vim.api.nvim_buf_get_lines(buf, 0, 1, false)[1] or "") == "# %%"
end, 10000)

local lines = vim.api.nvim_buf_get_lines(buf, 0, -1, false)
check("first marker", lines[1], "# %%")
check("code line", lines[2], "a = 6 * 7")
check("markdown marker", lines[4], "# %% [markdown]")
check("markdown body is commented", lines[5], "# # heading")
check("filetype", vim.bo[buf].filetype, "python")
check("not modified after load", vim.bo[buf].modified, false)

local cells = require("jnvim.cells").list(buf)
check("cell count", #cells, 3)
check("cell types", cells[2].cell_type, "markdown")

-- run the first cell, then the printing one
vim.api.nvim_win_set_cursor(0, { 2, 0 })
require("jnvim").run()
vim.api.nvim_win_set_cursor(0, { #lines, 0 })
require("jnvim").run()

local notebook = require("jnvim.notebook")
local st = notebook.get(buf)
wait("the kernel to produce output", function()
  for _, record in ipairs(st.records) do
    for _, line in ipairs(record.lines) do
      if line[1]:match("hi from kernel") then
        return true
      end
    end
  end
  return false
end)

wait("both cells to finish", function()
  if vim.tbl_count(st.tokens) > 0 then
    return false
  end
  local done = 0
  for _, record in ipairs(st.records) do
    if record.count then
      done = done + 1
    end
  end
  return done >= 2
end)

local texts = {}
for _, record in ipairs(st.records) do
  for _, line in ipairs(record.lines) do
    table.insert(texts, line[1])
  end
end
local joined = table.concat(texts, "\n")
check("stdout captured", joined:match("hi from kernel") ~= nil, true)
check("execute_result captured", joined:match("42") ~= nil, true)

-- outputs are rendered as virtual lines, never as buffer text
check("buffer text untouched", table.concat(vim.api.nvim_buf_get_lines(buf, 0, -1, false), "\n"),
  table.concat(lines, "\n"))
local marks = vim.api.nvim_buf_get_extmarks(buf, require("jnvim.output").ns, 0, -1, {})
check("output extmarks exist", #marks > 0, true)

-- save and read the file back
vim.cmd("write")
wait("the write to finish", function()
  return vim.bo[buf].modified == false
end, 10000)

local saved = vim.json.decode(table.concat(vim.fn.readfile(path), "\n"))
check("saved cell count", #saved.cells, 3)
check("saved cell types", saved.cells[2].cell_type, "markdown")
check("markdown uncommented on save", table.concat(saved.cells[2].source), "# heading")
check("code kept", table.concat(saved.cells[1].source), "a = 6 * 7")
check("execution count saved", saved.cells[1].execution_count ~= vim.NIL, true)
check("outputs saved", vim.json.encode(saved.cells[3].outputs):match("hi from kernel") ~= nil, true)
check("buffer clean after write", vim.bo[buf].modified, false)

-- editing above a cell keeps its output attached
local out = require("jnvim.output")
local before = out.row_of(buf, st.records[2])
vim.api.nvim_buf_set_lines(buf, 1, 1, false, { "# inserted" })
local after = out.row_of(buf, st.records[2])
check("output mark followed the edit", after, before + 1)

vim.cmd("write")
wait("the second write to finish", function()
  return vim.bo[buf].modified == false
end, 10000)
local resaved = vim.json.decode(table.concat(vim.fn.readfile(path), "\n"))
check("output still on the right cell after an edit",
  vim.json.encode(resaved.cells[3].outputs):match("hi from kernel") ~= nil, true)
check("the inserted line was saved", table.concat(resaved.cells[1].source), "# inserted\na = 6 * 7")

if #failures > 0 then
  io.stderr:write(("FAILED %d check(s):\n\n%s\n"):format(#failures, table.concat(failures, "\n\n")))
  io.stderr:write("\n--- saved file ---\n" .. table.concat(vim.fn.readfile(path), "\n") .. "\n")
  io.stderr:write("--- records ---\n" .. vim.inspect(st.records) .. "\n")
  vim.cmd("cquit 1")
end
print("nvim integration test passed")
vim.cmd("qall!")
