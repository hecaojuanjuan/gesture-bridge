@echo off
echo.
echo ========================================
echo 重新构建标准版自动居中固件
echo ========================================
echo.
echo 说明:
echo - 之前的固件使用了native分类器，无法直接烧录
echo - 现在构建标准版本，可以直接烧录
echo - 功能完整：人脸和手势自动居中
echo.
echo 这将需要约20分钟（构建15分钟 + 烧录3分钟）
echo.
pause

powershell -ExecutionPolicy Bypass -Command ^
"$py = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'; ^
Write-Host '清理旧构建...' -ForegroundColor Yellow; ^
Remove-Item -Recurse -Force .work\headvoice -ErrorAction SilentlyContinue; ^
Write-Host '开始构建...' -ForegroundColor Yellow; ^
Write-Host ''; ^
& $py tools/build.py headvoice build --stage 2 --vision face-hand --rotate-cw90; ^
Write-Host ''; ^
if (Test-Path .work\headvoice\apps\build\vb701n.bin) { ^
    Write-Host '✓ 构建成功！' -ForegroundColor Green; ^
    Get-Item .work\headvoice\apps\build\vb701n.bin; ^
    Write-Host ''; ^
    Write-Host '开始烧录...' -ForegroundColor Yellow; ^
    & $py tools/build.py headvoice flash --port COM3; ^
    Write-Host ''; ^
    Write-Host '✅ 完成！' -ForegroundColor Green; ^
} else { ^
    Write-Host '✗ 构建失败' -ForegroundColor Red; ^
}"

echo.
pause
