param([string]$Url = 'http://127.0.0.1:8765')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') -m scripts.simulate --url $Url

