param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
& $Python -c 'import sys; assert sys.version_info >= (3, 10); print(sys.version)'
if ($LASTEXITCODE) { throw 'Provide a working Python 3.10+ with -Python' }
$sdkDirectory = Join-Path $projectRoot 'vendor\official-sdk'
if (-not (Test-Path -LiteralPath "$sdkDirectory\esp-idf\tools\idf_tools.py")) {
    git clone https://gitee.com/xj-open/ljyd_xjwb03_agent_public_developer.git $sdkDirectory
    if ($LASTEXITCODE) { throw 'Official SDK clone failed' }
}
$sdkHead = git -C $sdkDirectory rev-parse HEAD
if ($sdkHead -ne '89020f5e04bf777ae1672b8f3d320bc6e0ef3e0c') {
    throw "SDK HEAD changed: $sdkHead. Review it before integration."
}
$env:IDF_TOOLS_PATH = Join-Path $projectRoot '.tools\espressif'
$env:IDF_PATH = Join-Path $sdkDirectory 'esp-idf'
$env:PYTHONUTF8 = '1'
& $Python "$sdkDirectory\esp-idf\tools\idf_tools.py" install --targets esp32s3
if ($LASTEXITCODE) { throw 'Toolchain installation failed' }
& $Python "$sdkDirectory\esp-idf\tools\idf_tools.py" install-python-env
if ($LASTEXITCODE) { throw 'IDF Python environment installation failed' }
& $Python -m pip install --target .tools/host ziglang==0.13.0 clang-format==19.1.7
if ($LASTEXITCODE) { throw 'Host tools installation failed' }
