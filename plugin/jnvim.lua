-- Entry point: commands + autocmds. Calling require("jnvim").setup() is optional.
if vim.g.loaded_jnvim then
  return
end
vim.g.loaded_jnvim = true

if vim.fn.has("nvim-0.9") == 0 then
  vim.notify("[jnvim] needs Neovim 0.9 or newer", vim.log.levels.ERROR)
  return
end

vim.api.nvim_create_user_command("Jnvim", function(opts)
  require("jnvim.commands").dispatch(opts)
end, {
  nargs = "*",
  desc = "jnvim: run and manage Jupyter notebooks",
  complete = function(lead, line)
    return require("jnvim.commands").complete(lead, line)
  end,
})

local group = vim.api.nvim_create_augroup("jnvim", { clear = true })

vim.api.nvim_create_autocmd("BufReadCmd", {
  group = group,
  pattern = "*.ipynb",
  callback = function(args)
    require("jnvim").open(args.buf, args.file)
  end,
})

vim.api.nvim_create_autocmd("BufWriteCmd", {
  group = group,
  pattern = "*.ipynb",
  callback = function(args)
    require("jnvim").save(args.buf, args.file)
  end,
})

vim.api.nvim_create_autocmd("ColorScheme", {
  group = group,
  callback = function()
    require("jnvim.output").setup_highlights()
  end,
})

vim.api.nvim_create_autocmd("VimLeavePre", {
  group = group,
  callback = function()
    require("jnvim.bridge").stop()
  end,
})
