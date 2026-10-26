-- Minimal config used by the headless tests: load only this plugin.
local root = vim.fn.fnamemodify(debug.getinfo(1, "S").source:sub(2), ":h:h")
vim.opt.runtimepath:prepend(root)
vim.opt.swapfile = false
vim.opt.more = false
vim.g.mapleader = " "
vim.g.maplocalleader = ","
if vim.env.JNVIM_PYTHON then
  vim.g.jnvim_python = vim.env.JNVIM_PYTHON
end
require("jnvim").setup({ python = vim.env.JNVIM_PYTHON })
