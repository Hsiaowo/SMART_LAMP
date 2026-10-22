param(
    [ValidateSet('nodemcuv2', 'd1_mini')][string]$Board = 'nodemcuv2',
    [string]$Port,
    [switch]$Upload,
    [switch]$Monitor
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PLATFORMIO_CORE_DIR = Join-Path $PSScriptRoot '.pio-core'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if ($Monitor) {
    if (-not $Port) { throw 'Supply the serial port, for example -Port COM5.' }
    & $pythonPath -m platformio device monitor --port $Port --baud 115200
} elseif ($Upload) {
    if (-not $Port) { throw 'Supply the verified serial port with -Port COM5.' }
    & $pythonPath -m platformio run -d firmware -e $Board -t upload --upload-port $Port
} else {
    & $pythonPath -m platformio run -d firmware -e $Board
}
