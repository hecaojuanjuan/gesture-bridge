$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$panelPython = Join-Path $taskRoot '.tools/espressif/python_env/idf5.4_py3.12_env/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $panelPython)) {
    throw 'Project Python environment is missing. Follow README setup instructions.'
}
$env:PYTHONUTF8 = '1'
& $panelPython (Join-Path $PSScriptRoot 'control_panel.py')
exit $LASTEXITCODE
