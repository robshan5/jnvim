# Sync the project into a WSL distro (native FS) and optionally run a command.
#   .\build\sync-wsl.ps1 -Distro OracleLinux_7_9 -Command "sh /root/jnvim/build/build-linux.sh"
param(
    [string]$Distro = "Ubuntu",
    [string]$Dest = "/root/jnvim",
    [string]$Command = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$unc = "\\wsl.localhost\$Distro" + ($Dest -replace "/", "\")

wsl -d $Distro -u root -- rm -rf "$Dest/jnvim" "$Dest/tests" "$Dest/build"
New-Item -ItemType Directory -Force -Path $unc | Out-Null
foreach ($dir in @("jnvim", "tests", "build")) {
    Copy-Item -Recurse -Force (Join-Path $root $dir) (Join-Path $unc $dir)
}
# shell scripts must have LF endings inside the distro
Get-ChildItem -Recurse -Path $unc -Filter *.sh | ForEach-Object {
    $text = (Get-Content $_.FullName -Raw) -replace "`r`n", "`n"
    [System.IO.File]::WriteAllText($_.FullName, $text)
}
Get-ChildItem -Recurse -Path $unc -Filter __pycache__ -Directory |
    ForEach-Object { Remove-Item -Recurse -Force $_.FullName }

if ($Command) { wsl -d $Distro -u root -- sh -lc $Command }
