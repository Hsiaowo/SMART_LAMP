$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create Python virtual environment.' }
}
& $pythonPath -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $pythonPath -m scripts.bootstrap
if ($LASTEXITCODE -ne 0) { throw 'Local configuration failed.' }
Write-Output 'Setup complete. Run .\run.ps1 and, in a second terminal, .\simulate.ps1'

