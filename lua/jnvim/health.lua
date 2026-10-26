-- :checkhealth jnvim
local config = require("jnvim.config")

local M = {}

local health = vim.health or require("health")
local start = health.start or health.report_start
local ok = health.ok or health.report_ok
local warn = health.warn or health.report_warn
local error_ = health.error or health.report_error

local function run(python, code)
  local out = vim.fn.system({ python, "-c", code })
  return vim.v.shell_error == 0, vim.trim(out)
end

function M.check()
  start("jnvim.nvim")

  if vim.fn.has("nvim-0.9") == 1 then
    ok("Neovim " .. tostring(vim.version()))
  else
    error_("Neovim 0.9 or newer is required")
  end

  local python = config.python()
  if vim.fn.executable(python) ~= 1 then
    error_(("python not found: %s"):format(python),
      { "set it with require('jnvim').setup{ python = '/path/to/python' }" })
    return
  end
  local good, version = run(python, "import sys;print(sys.version.split()[0])")
  if good then
    ok(("python: %s (%s)"):format(python, version))
  else
    error_(("cannot run %s"):format(python))
    return
  end

  local has_client, client = run(python, "import jupyter_client;print(jupyter_client.__version__)")
  if has_client then
    ok("jupyter_client " .. client)
  else
    error_("jupyter_client is missing", { ("%s -m pip install jupyter_client ipykernel"):format(python) })
    return
  end

  local has_kernel, kernel = run(python, "import ipykernel;print(ipykernel.__version__)")
  if has_kernel then
    ok("ipykernel " .. kernel)
  else
    warn("ipykernel is missing (no python3 kernel to run)",
      { ("%s -m pip install ipykernel"):format(python) })
  end

  local listed, kernels = run(python,
    "from jupyter_client.kernelspec import KernelSpecManager as K;print(', '.join(sorted(K().get_all_specs())))")
  if listed and kernels ~= "" then
    ok("kernels: " .. kernels)
  else
    warn("no kernelspecs found", { ("%s -m ipykernel install --user"):format(python) })
  end

  local root = require("jnvim.bridge").root()
  if vim.fn.filereadable(root .. "/python/jnvim/__main__.py") == 1 then
    ok("bridge: " .. root .. "/python/jnvim")
  else
    error_("the python bridge is missing from " .. root .. "/python")
  end

  local images = require("jnvim.image")
  local impl = images.backend()
  if impl then
    ok("images: " .. impl.name)
  else
    (health.info or warn)("no image backend: figures show as [image/png WxH] placeholders", {
      "install 3rd/image.nvim or folke/snacks.nvim (snacks.image)",
      "needs a terminal with kitty graphics or sixel (kitty, wezterm, ghostty)",
      "`:Jnvim image-open` opens the figure in an external viewer meanwhile",
    })
  end
end

return M
