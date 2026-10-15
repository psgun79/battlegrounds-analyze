$ErrorActionPreference = 'Stop'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    & .\.venv\Scripts\python.exe -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
    & .\.venv\Scripts\python.exe -m build
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
    & .\.venv\Scripts\python.exe -m bg_review replay tests/fixtures/sample.Power.log --date 2026-09-14 --output examples
    if ($LASTEXITCODE -ne 0) { throw 'Replay failed' }
} finally { Pop-Location }
