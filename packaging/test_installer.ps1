param(
    [Parameter(Mandatory=$true)][string]$Installer,
    [Parameter(Mandatory=$true)][string]$Destination
)
$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$testRoot = [IO.Path]::GetFullPath((Join-Path $workspace 'build')) + [IO.Path]::DirectorySeparatorChar
$testDestination = [IO.Path]::GetFullPath($Destination)
if (-not $testDestination.StartsWith($testRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Test destination must be inside this project build directory.'
}
if (Test-Path -LiteralPath $testDestination) { throw 'Use a new, empty test destination.' }
$setupExe = (Resolve-Path -LiteralPath $Installer).Path
New-Item -ItemType Directory -Path $testDestination | Out-Null
$legacyConfig = Join-Path $testDestination 'ha_widgets_config.json'
'{"ha_token":"","tiles":[],"theme":"dark","test_marker":"legacy"}' |
    Set-Content -LiteralPath $legacyConfig -Encoding utf8

function Invoke-TestInstall([string]$label) {
    $log = Join-Path $testDestination ($label + '.log')
    $setupArgs = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/TESTINSTALL=1',
        ('/DIR="' + $testDestination + '"'), ('/LOG="' + $log + '"'))
    $setupProcess = Start-Process -FilePath $setupExe -ArgumentList $setupArgs -WindowStyle Hidden -PassThru -Wait
    if ($setupProcess.ExitCode -ne 0) { throw "Installer $label failed: $($setupProcess.ExitCode). See $log" }
}

Invoke-TestInstall 'first-install'
$userConfig = Join-Path $testDestination 'test-user-data\ha_widgets_config.json'
if ((Get-FileHash -LiteralPath $legacyConfig).Hash -ne (Get-FileHash -LiteralPath $userConfig).Hash) {
    throw 'Legacy settings migration failed.'
}
$installedExe = Join-Path $testDestination 'HA Widgets.exe'
$originalExeHash = (Get-FileHash -LiteralPath $installedExe).Hash
'{"ha_token":"","tiles":[],"theme":"light","test_marker":"keep-on-upgrade"}' |
    Set-Content -LiteralPath $userConfig -Encoding utf8
$configHash = (Get-FileHash -LiteralPath $userConfig).Hash
# Simulate a damaged/outdated executable; the next installer must replace it.
Set-Content -LiteralPath $installedExe -Value 'old executable fixture' -Encoding ascii
$internal = Join-Path $testDestination '_internal'
New-Item -ItemType Directory -Force -Path $internal | Out-Null
Set-Content -LiteralPath (Join-Path $internal 'icuuc.dll') -Value 'incompatible old ICU fixture'
Set-Content -LiteralPath (Join-Path $internal 'icudt78.dll') -Value 'obsolete ICU data fixture'
Invoke-TestInstall 'upgrade'
if ((Get-FileHash -LiteralPath $installedExe).Hash -ne $originalExeHash) { throw 'Upgrade did not restore application files.' }
if ((Get-FileHash -LiteralPath $userConfig).Hash -ne $configHash) { throw 'Upgrade changed user settings.' }
if ((Test-Path -LiteralPath (Join-Path $internal 'icuuc.dll')) -or
    (Test-Path -LiteralPath (Join-Path $internal 'icudt78.dll'))) { throw 'Upgrade retained incompatible ICU files.' }
if (Test-Path -LiteralPath (Join-Path $testDestination 'unins000.exe')) { throw 'Test mode unexpectedly registered an uninstaller.' }
Write-Host 'PASS: first install, legacy settings migration, file replacement, and settings-preserving upgrade.'
