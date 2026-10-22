param([int]$Port = 8765, [switch]$LoopbackOnly)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run .\setup.ps1 first.' }
$listenAddress = if ($LoopbackOnly) { '127.0.0.1' } else { '0.0.0.0' }
& $pythonPath -m backend --host $listenAddress --port $Port

