# Sync this plugin into a WSL distro and run a command there.
#   .\scripts\sync-wsl.ps1 -Distro Ubuntu -Command "sh /root/jnvim/tests/run.sh"
param(
    [string]$Distro = "Ubuntu",
    [string]$Dest = "/root/jnvim",
    [string]$Command = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$unc = "\\wsl.localhost\$Distro" + ($Dest -replace "/", "\")
$dirs = @("lua", "plugin", "python", "tests", "doc")
# legacy layout from the old curses app, removed so it cannot shadow the plugin
$stale = @("jnvim", "build", "dist")

wsl -d $Distro -u root -- rm -rf (($dirs + $stale) | ForEach-Object { "$Dest/$_" })
New-Item -ItemType Directory -Force -Path $unc | Out-Null
foreach ($dir in $dirs) {
    $src = Join-Path $root $dir
    if (Test-Path $src) { Copy-Item -Recurse -Force $src (Join-Path $unc $dir) }
}
Get-ChildItem -Recurse -Path $unc -Filter *.sh | ForEach-Object {
    $text = (Get-Content $_.FullName -Raw) -replace "`r`n", "`n"
    [System.IO.File]::WriteAllText($_.FullName, $text)
}
Get-ChildItem -Recurse -Path $unc -Filter __pycache__ -Directory |
    ForEach-Object { Remove-Item -Recurse -Force $_.FullName }

if ($Command) { wsl -d $Distro -u root -- sh -lc $Command }
