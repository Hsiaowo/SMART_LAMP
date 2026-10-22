$ErrorActionPreference = 'Stop'
$workspacePath = $PSScriptRoot
$venvPythonPath = Join-Path $workspacePath '.venv\Scripts\python.exe'
# Only stop project-local Python launchers running these two known modules.
# taskkill /T also closes the child interpreter used by Python's Windows venv.
$launchers = Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -eq $venvPythonPath -and
    $_.CommandLine -match ' -m (backend|scripts\.simulate)( |$)'
}
foreach ($launcher in $launchers) {
    & taskkill.exe /PID $launcher.ProcessId /T /F
}
if (-not $launchers) { Write-Output 'No matching project demo processes are running.' }

