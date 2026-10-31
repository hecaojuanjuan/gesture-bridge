@echo off
echo.
echo ========================================
echo 重新构建 baseline 固件（修复舵机零位）
echo ========================================
echo.
echo 修改内容：
echo - 舵机零位从 1450us 改为 1500us
echo - 修复 1500us 时大幅低头的问题
echo.

powershell -ExecutionPolicy Bypass -Command ^
"$py = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'; ^
Write-Host '清理旧构建...' -ForegroundColor Yellow; ^
Remove-Item -Recurse -Force .work\baseline\apps\build -ErrorAction SilentlyContinue; ^
Write-Host '开始构建 baseline 固件...' -ForegroundColor Yellow; ^
Write-Host ''; ^
& $py tools/build.py baseline build; ^
Write-Host ''; ^
if (Test-Path .work\baseline\apps\build\vb701n.bin) { ^
    Write-Host '✓ 构建成功！' -ForegroundColor Green; ^
    Get-Item .work\baseline\apps\build\vb701n.bin; ^
    Write-Host ''; ^
    Write-Host '开始烧录到 COM3...' -ForegroundColor Yellow; ^
    & $py tools/build.py baseline flash --port COM3; ^
    Write-Host ''; ^
    Write-Host '✅ 完成！舵机零位已修复为 1500us' -ForegroundColor Green; ^
} else { ^
    Write-Host '✗ 构建失败' -ForegroundColor Red; ^
}"
