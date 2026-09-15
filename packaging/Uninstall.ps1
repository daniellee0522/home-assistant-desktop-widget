<#
    Removes what Install.ps1 put in place.

        powershell -ExecutionPolicy Bypass -File packaging\Uninstall.ps1

    Leaves the settings under %APPDATA%\HA Widgets alone unless -Purge is
    given: reinstalling and finding your accessories still there is worth
    more than a tidy uninstall, and the folder is a few kilobytes.
#>
param([switch]$Purge)

$ErrorActionPreference = 'SilentlyContinue'
$name = 'HA Widgets'

Get-Process -Name $name | ForEach-Object { $_.Kill(); $_.WaitForExit(5000) }

$paths = @(
    (Join-Path $env:LOCALAPPDATA $name),
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\$name.lnk"),
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\$name.lnk")
)
if ($Purge) { $paths += (Join-Path $env:APPDATA $name) }
foreach ($p in $paths) {
    if (Test-Path $p) { Remove-Item -Recurse -Force $p; Write-Host "Removed $p" }
}
Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name $name
Write-Host "Done."
