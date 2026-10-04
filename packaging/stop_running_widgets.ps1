<# Close verified HA Widgets copies before an upgrade, including portable releases. #>
param([string]$TestRoot)
$ErrorActionPreference = 'Stop'
$testPrefix = if ($TestRoot) { [IO.Path]::GetFullPath($TestRoot).TrimEnd('\') + '\' } else { $null }
$targets = @(Get-Process -Name 'HA Widgets' -ErrorAction SilentlyContinue | Where-Object {
    try {
        $candidatePath = $_.Path
        if (-not $candidatePath) { return $false }
        if ($testPrefix -and -not $candidatePath.StartsWith($testPrefix, [StringComparison]::OrdinalIgnoreCase)) { return $false }
        $identity = (Get-Item -LiteralPath $candidatePath).VersionInfo
        return $identity.ProductName -eq 'HA Widgets' -and $identity.FileDescription -eq 'Home Assistant Desktop Widgets'
    } catch { return $false }
})
foreach ($target in $targets) {
    if (-not $target.HasExited) {
        Write-Output ('Closing verified HA Widgets process ' + $target.Id)
        Stop-Process -Id $target.Id -Force -ErrorAction Stop
    }
}
foreach ($target in $targets) {
    # Get-Process can return an already-exited object. Its WaitForExit may
    # time out despite HasExited being true; only wait on a live process.
    if (-not $target.HasExited -and -not $target.WaitForExit(8000)) {
        throw 'An older HA Widgets process did not exit.'
    }
}
