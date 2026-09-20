param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version,
    [string]$Iscc
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$versionFile = Join-Path $root 'VERSION'
[System.IO.File]::WriteAllText($versionFile, "$Version`n", [System.Text.UTF8Encoding]::new($false))

Push-Location $root
try {
    python -m unittest discover -s tests -p 'test_*.py'
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
    $buildArgs = @('packaging/build.py', '--version', $Version, '--installer')
    if ($Iscc) { $buildArgs += @('--iscc', $Iscc) }
    python @buildArgs
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
    $output = Join-Path $root "dist/$Version"
    Write-Host "Release files: $output"
    Get-ChildItem -LiteralPath $output -Filter 'HA-Widgets-Setup-*' |
        Select-Object Name,Length,FullName | Format-Table -AutoSize
} finally {
    Pop-Location
}
