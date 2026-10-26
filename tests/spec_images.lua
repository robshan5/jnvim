-- Matplotlib figures end to end: the kernel's PNG reaches a real file and the
-- image backend is asked to draw it at the cell's output row.
--   nvim --headless --clean -u tests/minimal_init.lua -l tests/spec_images.lua
local failures = {}

local function check(name, got, want)
  if got ~= want then
    table.insert(failures, ("%s\n   got : %s\n   want: %s"):format(name, vim.inspect(got), vim.inspect(want)))
  end
end

local function wait(desc, fn, ms)
  if not vim.wait(ms or 60000, fn, 50) then
    table.insert(failures, "timeout waiting for " .. desc)
    return false
  end
  return true
end

-- a backend that records what it was asked to draw
local drawn = {}
require("jnvim.image").set_backend({
  name = "test",
  show = function(bufnr, path, row, opts)
    table.insert(drawn, { bufnr = bufnr, path = path, row = row, max_height = opts.max_height })
    return { id = #drawn }
  end,
  clear = function(handle)
    handle.cleared = true
  end,
})

local tmp = vim.fn.tempname()
vim.fn.mkdir(tmp, "p")
local path = tmp .. "/figure.ipynb"
vim.fn.writefile({ vim.json.encode({
  cells = {
    {
      cell_type = "code",
      source = {
        "%matplotlib inline\n",
        "import matplotlib.pyplot as plt\n",
        "fig, ax = plt.subplots(figsize=(4, 3), dpi=50)\n",
        "ax.plot([0, 1, 4, 9])\n",
        "print('plotted')\n",
        "fig",
      },
      outputs = {},
      execution_count = vim.NIL,
      metadata = vim.empty_dict(),
    },
  },
  metadata = { kernelspec = { name = "python3", display_name = "Python 3", language = "python" } },
  nbformat = 4,
  nbformat_minor = 5,
}) }, path)

vim.cmd.edit(vim.fn.fnameescape(path))
local buf = vim.api.nvim_get_current_buf()
wait("the notebook to load", function()
  return (vim.api.nvim_buf_get_lines(buf, 0, 1, false)[1] or "") == "# %%"
end, 10000)

vim.api.nvim_win_set_cursor(0, { 2, 0 })
require("jnvim").run()

local st = require("jnvim.notebook").get(buf)
wait("the figure to be drawn", function()
  return #drawn >= 1
end)
local first = drawn[1] or {}

local record = st.records[1]
local specs = require("jnvim.image").specs(record)
check("one image", #specs, 1)
local spec = specs[1] or {}
if spec.path then
  check("mime", spec.mime, "image/png")
  check("file written", vim.fn.filereadable(spec.path) == 1, true)
  check("width parsed", type(spec.width) == "number" and spec.width > 0, true)
  check("height parsed", type(spec.height) == "number" and spec.height > 0, true)
  check("png magic", (vim.fn.readfile(spec.path, "b", 1)[1] or ""):sub(2, 4), "PNG")
  local label
  for _, entry in ipairs(record.lines) do
    if entry[2] == "image" then
      label = entry[1]
    end
  end
  check("label has the pixel size", label, ("[image/png %dx%d]"):format(spec.width, spec.height))
end
check("backend drew it", #drawn >= 1, true)
check("drawn file matches", first.path, spec.path)
check("drawn in this buffer", first.bufnr, buf)
check("drawn at the output row", first.row, record.out_row)

-- stdout is still rendered as text, the image placeholder is not
local text = {}
for _, entry in ipairs(record.lines) do
  if entry[2] ~= "image" then
    table.insert(text, entry[1])
  end
end
check("stdout kept", vim.tbl_contains(text, "plotted"), true)
local virt = vim.api.nvim_buf_get_extmarks(buf, require("jnvim.output").ns, 0, -1, { details = true })
local rendered = {}
for _, mark in ipairs(virt) do
  for _, line in ipairs((mark[4] or {}).virt_lines or {}) do
    table.insert(rendered, line[1][1])
  end
end
local placeholder = spec.width and ("  [image/png %dx%d]"):format(spec.width, spec.height) or ""
check("placeholder replaced by the image", vim.tbl_contains(rendered, placeholder), false)
check("text output still shown", vim.tbl_contains(rendered, "  plotted"), true)

-- the png survives a save/reload round trip
vim.cmd("write")
wait("the write to finish", function()
  return vim.bo[buf].modified == false
end, 10000)
check("png embedded in the file",
  table.concat(vim.fn.readfile(path), "\n"):match("image/png") ~= nil, true)

vim.cmd("bwipeout!")
vim.cmd.edit(vim.fn.fnameescape(path))
local reopened = vim.api.nvim_get_current_buf()
wait("the reopened notebook to render its image", function()
  local state = require("jnvim.notebook").get(reopened)
  if not state then
    return false
  end
  for _, rec in ipairs(state.records) do
    if #require("jnvim.image").specs(rec) > 0 then
      return true
    end
  end
  return false
end, 15000)
local reloaded = require("jnvim.image").specs(require("jnvim.notebook").get(reopened).records[1])
check("image restored from the file", #reloaded, 1)
check("restored file exists", reloaded[1] and vim.fn.filereadable(reloaded[1].path) == 1, true)

-- without a backend the placeholder comes back
require("jnvim.image").set_backend(nil)
require("jnvim.output").render(reopened, require("jnvim.notebook").get(reopened).records[1])
local marks = vim.api.nvim_buf_get_extmarks(reopened, require("jnvim.output").ns, 0, -1, { details = true })
local fallback = {}
for _, mark in ipairs(marks) do
  for _, line in ipairs((mark[4] or {}).virt_lines or {}) do
    table.insert(fallback, line[1][1])
  end
end
check("placeholder without a backend", vim.tbl_contains(fallback, placeholder), true)

if #failures > 0 then
  io.stderr:write(("FAILED %d check(s):\n\n%s\n"):format(#failures, table.concat(failures, "\n\n")))
  io.stderr:write("--- drawn ---\n" .. vim.inspect(drawn) .. "\n")
  io.stderr:write("--- lines ---\n" .. vim.inspect(record.lines) .. "\n")
  vim.cmd("cquit 1")
end
print("image test passed")
vim.cmd("qall!")
