<# Launch the current release installer. Existing startup preferences are preserved. #>
param(
    [switch]$NoStartup,
    [switch]$NoLaunch,
    [string]$Version
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Version) { $Version = (Get-Content -LiteralPath (Join-Path $projectRoot 'VERSION') -Raw).Trim() }
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Version must be MAJOR.MINOR.PATCH.' }
$installer = Join-Path $projectRoot "dist\$Version\HA-Widgets-Setup-$Version.exe"
if (-not (Test-Path -LiteralPath $installer)) {
    throw "Installer not found. Run: python packaging/build.py --version $Version --installer"
}
$checksumFile = $installer + '.sha256'
if (-not (Test-Path -LiteralPath $checksumFile)) {
    throw 'The installer build is not complete or verified yet. Wait for the build to finish.'
}
$expectedHash = ((Get-Content -LiteralPath $checksumFile -Raw).Trim() -split '\s+')[0]
if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ne $expectedHash) {
    throw 'Installer checksum mismatch. The build may still be in progress; rebuild before installing.'
}
$installerArgs = @('/NORESTART')
if ($NoLaunch) { $installerArgs += '/NOLAUNCH=1' }
# NoStartup remains accepted for older callers; this installer never adds startup entries.
$installProcess = Start-Process -FilePath $installer -ArgumentList $installerArgs -PassThru -Wait
if ($installProcess.ExitCode -ne 0) { throw "Installer exited with code $($installProcess.ExitCode)." }
