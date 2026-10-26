-- Comment characters for the percent format; mirrors python/jnvim/percent.py.
local M = {}

M.comments = {
  python = "#", python3 = "#", julia = "#", ruby = "#", r = "#", sh = "#", bash = "#",
  javascript = "//", typescript = "//", c = "//", cpp = "//", rust = "//", scala = "//",
  sql = "--", haskell = "--", matlab = "%", octave = "%",
}

function M.comment_char(language)
  return M.comments[(language or "python"):lower()] or "#"
end

function M.marker(language, cell_type)
  local char = M.comment_char(language)
  if cell_type == "markdown" then
    return char .. " %% [markdown]"
  elseif cell_type == "raw" then
    return char .. " %% [raw]"
  end
  return char .. " %%"
end

return M
