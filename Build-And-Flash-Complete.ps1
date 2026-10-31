$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "人脸和手势自动居中固件 - 完整构建流程" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$py = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$port = 'COM3'

# 步骤1：清理
Write-Host "[1/3] 清理旧构建..." -ForegroundColor Yellow
if (Test-Path ".work\headvoice\apps\build") {
    Remove-Item -Recurse -Force ".work\headvoice\apps\build"
}
if (Test-Path ".work\headvoice\apps\sdkconfig") {
    Remove-Item -Force ".work\headvoice\apps\sdkconfig"
}
Write-Host "✓ 清理完成" -ForegroundColor Green
Write-Host ""

# 步骤2：构建
Write-Host "[2/3] 构建固件（预计10-15分钟）..." -ForegroundColor Yellow
Write-Host "配置: --stage 2 --vision face-hand --rotate-cw90" -ForegroundColor Gray
Write-Host ""

try {
    & $py tools/build.py headvoice build --stage 2 --vision face-hand --rotate-cw90

    if (-not (Test-Path ".work\headvoice\apps\build\vb701n.bin")) {
        throw "固件文件未生成"
    }

    Write-Host ""
    Write-Host "✓ 构建完成" -ForegroundColor Green
    $firmware = Get-Item ".work\headvoice\apps\build\vb701n.bin"
    Write-Host "固件: $($firmware.FullName)" -ForegroundColor Gray
    Write-Host "大小: $([math]::Round($firmware.Length/1MB, 2)) MB" -ForegroundColor Gray
    Write-Host "时间: $($firmware.LastWriteTime)" -ForegroundColor Gray
    Write-Host ""

} catch {
    Write-Host ""
    Write-Host "✗ 构建失败: $_" -ForegroundColor Red
    exit 1
}

# 步骤3：烧录
Write-Host "[3/3] 烧录固件到设备..." -ForegroundColor Yellow
Write-Host "端口: $port" -ForegroundColor Gray
Write-Host ""

try {
    & $py tools/build.py headvoice flash --port $port

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "✅ 完成！设备正在重启..." -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "功能说明:" -ForegroundColor Yellow
    Write-Host "  • 伸出手 → 云台跟踪手部居中" -ForegroundColor White
    Write-Host "  • 收回手 → 云台切换到人脸居中" -ForegroundColor White
    Write-Host "  • 全自动，无需手动命令" -ForegroundColor White
    Write-Host ""
    Write-Host "查看串口输出:" -ForegroundColor Yellow
    Write-Host "  $py tools/build.py headvoice monitor --port $port" -ForegroundColor Gray
    Write-Host ""
    Write-Host "查看详细文档: FINAL_DELIVERY.md" -ForegroundColor Yellow
    Write-Host ""

} catch {
    Write-Host ""
    Write-Host "✗ 烧录失败: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "请检查:" -ForegroundColor Yellow
    Write-Host "  1. 设备是否连接到 $port" -ForegroundColor White
    Write-Host "  2. 是否有其他程序占用串口" -ForegroundColor White
    Write-Host "  3. USB线缆是否正常" -ForegroundColor White
    Write-Host ""
    exit 1
}
