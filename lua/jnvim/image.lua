-- Inline images for cell outputs.
--
-- Neovim cannot draw images itself, so this delegates to whatever terminal
-- image plugin is installed (image.nvim or snacks.image). Without one, the
-- output keeps its "[image/png 640x480]" placeholder and `:Jnvim image-open`
-- hands the file to the system viewer.
local config = require("jnvim.config")

local M = {}

local backend = nil
local detected = false

local function image_nvim()
  local ok, api = pcall(require, "image")
  if not ok or type(api) ~= "table" or not api.from_file then
    return nil
  end
  return {
    name = "image.nvim",
    show = function(bufnr, path, row, opts)
      local win = vim.fn.bufwinid(bufnr)
      if win == -1 then
        return nil
      end
      local ok_img, img = pcall(api.from_file, path, {
        id = opts.id,
        buffer = bufnr,
        window = win,
        with_virtual_padding = true,
        inline = true,
        x = 0,
        y = row,
        max_height = opts.max_height,
      })
      if not ok_img or not img then
        return nil
      end
      pcall(function()
        img:render()
      end)
      return img
    end,
    clear = function(handle)
      pcall(function()
        handle:clear()
      end)
    end,
  }
end

local function snacks_image()
  local ok, snacks = pcall(require, "snacks")
  if not ok or not snacks.image or not snacks.image.placement then
    return nil
  end
  return {
    name = "snacks.image",
    show = function(bufnr, path, row, opts)
      local ok_img, placement = pcall(snacks.image.placement.new, bufnr, path, {
        pos = { row + 1, 0 },
        inline = true,
        max_height = opts.max_height,
      })
      return ok_img and placement or nil
    end,
    clear = function(handle)
      pcall(function()
        handle:close()
      end)
    end,
  }
end

local BACKENDS = {
  ["image.nvim"] = image_nvim,
  ["snacks.image"] = snacks_image,
}

function M.detect()
  local wanted = config.options.output.images.backend
  if wanted == "none" then
    return nil
  end
  if wanted ~= "auto" then
    local factory = BACKENDS[wanted]
    return factory and factory() or nil
  end
  for _, name in ipairs({ "image.nvim", "snacks.image" }) do
    local found = BACKENDS[name]()
    if found then
      return found
    end
  end
  return nil
end

function M.backend()
  if not detected then
    detected = true
    backend = M.detect()
  end
  return backend
end

--- Install a custom backend (also used by the tests).
---@param custom table|nil { name, show(bufnr, path, row, opts), clear(handle) }
function M.set_backend(custom)
  backend = custom
  detected = true
end

function M.available()
  return config.options.output.images.enabled and M.backend() ~= nil
end

--- Image entries of a record, in output order.
function M.specs(record)
  local specs = {}
  for _, entry in ipairs(record.lines or {}) do
    if entry[2] == "image" and type(entry[3]) == "table" and entry[3].path then
      table.insert(specs, entry[3])
    end
  end
  return specs
end

function M.clear(record)
  if not record.image_handles then
    return
  end
  local impl = M.backend()
  for _, handle in ipairs(record.image_handles) do
    if impl then
      impl.clear(handle)
    end
  end
  record.image_handles = nil
end

--- Place (or re-place) every image of a record at `row`.
function M.sync(bufnr, record, row)
  local impl = M.backend()
  if not impl or not config.options.output.images.enabled or record.hidden then
    M.clear(record)
    return 0
  end
  local specs = M.specs(record)
  M.clear(record)
  if #specs == 0 or not row then
    return 0
  end
  record.image_handles = {}
  for index, spec in ipairs(specs) do
    if vim.fn.filereadable(spec.path) == 1 then
      local handle = impl.show(bufnr, spec.path, row, {
        id = ("jnvim-%d-%s-%d"):format(bufnr, tostring(record):gsub("%W", ""), index),
        max_height = config.options.output.images.max_height,
      })
      if handle then
        table.insert(record.image_handles, handle)
      end
    end
  end
  return #record.image_handles
end

--- Open the first image of a record with the system viewer.
function M.open_external(record)
  local specs = M.specs(record)
  if #specs == 0 then
    vim.notify("[jnvim] no image in this cell", vim.log.levels.INFO)
    return
  end
  local openers = { "xdg-open", "open", "wslview", "explorer.exe" }
  for _, exe in ipairs(openers) do
    if vim.fn.executable(exe) == 1 then
      vim.fn.jobstart({ exe, specs[1].path }, { detach = true })
      return
    end
  end
  vim.notify("[jnvim] image saved to " .. specs[1].path, vim.log.levels.INFO)
end

return M
