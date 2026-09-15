<#
    Installs HA Widgets for the current user, with nothing but PowerShell.

        powershell -ExecutionPolicy Bypass -File packaging\Install.ps1

    Copies the build into %LOCALAPPDATA%, puts it in the Start menu, and
    offers to start it with Windows. Per user and no elevation: this is a
    gadget for one person's desktop, and it keeps its settings under
    %APPDATA% anyway.

    packaging\installer.iss makes a real setup.exe out of the same build
    when Inno Setup is available; this is the path that needs no tools.
#>
param(
    [switch]$NoStartup,
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
$name    = 'HA Widgets'
$source  = Join-Path (Split-Path -Parent $PSScriptRoot) "dist\$name"
$target  = Join-Path $env:LOCALAPPDATA $name
$exe     = Join-Path $target "$name.exe"

if (-not (Test-Path (Join-Path $source "$name.exe"))) {
    throw "No build found at $source - run `python packaging\build.py` first."
}

Get-Process -Name $name -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "Stopping the running copy..."
    $_.Kill(); $_.WaitForExit(5000)
}

Write-Host "Installing to $target"
if (Test-Path $target) { Remove-Item -Recurse -Force $target }
New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item -Recurse -Force (Join-Path $source '*') $target

function New-Shortcut($linkPath, $targetPath) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($linkPath)
    $link.TargetPath = $targetPath
    $link.WorkingDirectory = Split-Path -Parent $targetPath
    $link.IconLocation = $targetPath
    $link.Save()
}

$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
New-Shortcut (Join-Path $startMenu "$name.lnk") $exe
Write-Host "Added to the Start menu."

if (-not $NoStartup) {
    $startup = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
    New-Shortcut (Join-Path $startup "$name.lnk") $exe
    Write-Host "Set to start with Windows."
}

if (-not $NoLaunch) {
    Start-Process $exe
    Write-Host "Started."
}
Write-Host "Done. Settings live in $env:APPDATA\$name."
