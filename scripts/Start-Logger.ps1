param(
    [switch]$Background,
    [string]$OutputDirectory = "$env:LOCALAPPDATA\BattlegroundsReview\output",
    [string]$LogRoot = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    Push-Location $projectRoot
    try {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
        & $pythonPath -m pip install .
        if ($LASTEXITCODE -ne 0) { throw 'Package installation failed.' }
    } finally { Pop-Location }
}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$loggerArgs = @('-m', 'bg_review', 'watch', '--output', $OutputDirectory)
if ($LogRoot) { $loggerArgs += @('--log-root', $LogRoot) }
if ($Background) {
    # Start-Process accepts a Windows command-line string. Reject embedded quotes in path arguments.
    foreach ($arg in $loggerArgs) { if ($arg.Contains('"')) { throw 'Paths cannot contain double quotes.' } }
    $quotedArgs = ($loggerArgs | ForEach-Object { '"' + $_ + '"' }) -join ' '
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $process = Start-Process -FilePath $pythonPath -ArgumentList $quotedArgs -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $OutputDirectory "watch-$stamp.stdout.log") `
        -RedirectStandardError (Join-Path $OutputDirectory "watch-$stamp.stderr.log")
    Write-Output "Logger launched (PID $($process.Id)). Status: $OutputDirectory\watch-status.json"
} else {
    Push-Location $projectRoot
    try { & $pythonPath @loggerArgs } finally { Pop-Location }
}
