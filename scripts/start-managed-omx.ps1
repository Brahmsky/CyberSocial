param(
    [string]$SessionName = "cyber-social"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

if (-not (Get-Command tmux -ErrorAction SilentlyContinue)) {
    throw "tmux is not available on PATH."
}

if (-not (Get-Command omx -ErrorAction SilentlyContinue)) {
    throw "omx is not available on PATH."
}

$escapedRepoRoot = $repoRoot.Replace("'", "''")
$launchCommand = "powershell -NoLogo -NoExit -Command ""Set-Location '$escapedRepoRoot'; omx"""

Write-Host "Launching managed OMX session '$SessionName' in $repoRoot"
tmux new-session -A -s $SessionName -c $repoRoot $launchCommand
