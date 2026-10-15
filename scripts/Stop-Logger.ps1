param([string]$OutputDirectory = "$env:LOCALAPPDATA\BattlegroundsReview\output")
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $OutputDirectory)) { Write-Output 'No logger output directory.'; exit }
Set-Content -LiteralPath (Join-Path $OutputDirectory 'stop-request') -Value 'stop' -Encoding ascii
Write-Output 'Graceful stop requested. The logger will export the current match before exiting.'
