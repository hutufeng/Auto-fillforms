# -*- coding: utf-8 -*-
<#
.SYNOPSIS
    身份证OCR · 商业单文件/绿色便携版一键打包脚本
.DESCRIPTION
    利用 PyInstaller 自动将 Python、Flask、本地 OCR 与前端资源封装为独立可执行文件
#>

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  🪪 身份证OCR · 商业单文件 / 绿色免安装版打包构建器" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan

# 检查 Python 环境
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) {
    $py = "C:\Users\hutu_\AppData\Local\Programs\Python\Python310\python.exe"
}
Write-Host "[1/4] 使用 Python 解释器: $py" -ForegroundColor Yellow

# 检查并安装 PyInstaller
Write-Host "[2/4] 检查打包必备工具 (PyInstaller)..." -ForegroundColor Yellow
& $py -m pip install --quiet pyinstaller pywebview cryptography

# 清理旧的构建残留
if (Test-Path ".\build") { Remove-Item -Path ".\build" -Recurse -Force }
if (Test-Path ".\dist") { Remove-Item -Path ".\dist" -Recurse -Force }

Write-Host "[3/4] 开始执行 PyInstaller 单文件无黑框封装..." -ForegroundColor Yellow

# 打包命令：
# -F 单文件
# -w 无控制台黑框
# --add-data 打包 static 和 templates
& $py -m PyInstaller `
    --noconfirm `
    --onefile `
    --windowed `
    --name "身份证OCR" `
    --add-data "static;static" `
    --add-data "templates;templates" `
    --hidden-import "cryptography" `
    --hidden-import "jinja2" `
    --hidden-import "openpyxl" `
    --hidden-import "docxtpl" `
    run_desktop.py

Write-Host "[4/4] 打包完成！生成闲鱼发货便携包与买家指南..." -ForegroundColor Green

# 生成买家配套说明书
$GuideContent = @"
==================================================
  🪪 身份证OCR · 商业标准版 使用与激活指南
==================================================

【首次使用说明】
1. 双击运行当前目录下的【身份证OCR.exe】（无需配置任何环境，纯绿色软件）。
2. 打开软件后，点击软件顶部或弹窗中的【一键复制机器码】。
3. 将机器码发送给闲鱼卖家，卖家核验后将为您发放 16 位专属激活卡密。
4. 在软件输入框中粘贴卡密，点击【立即联网验证激活】，即可永久解锁核心功能！

【功能亮点】
- 📷 单张正/反面高精度毫秒级提取（支持单图正反合图自动拆分）
- 📁 批量图片拖拽，自动按人名分组配对识别
- 📝 自定义 Word / Excel 模板智能套打导出
- 🔒 纯离线隐私保护，图片绝不上送第三方，政企事业单位合规无忧

祝您使用愉快！如有疑问请联系闲鱼卖家。
"@

$GuidePath = ".\dist\使用与激活指南.txt"
[System.IO.File]::WriteAllText($GuidePath, $GuideContent, [System.Text.Encoding]::UTF8)

Write-Host "`n✅ 构建成果已存放于 dist/ 目录：" -ForegroundColor Cyan
Write-Host "   📁 dist\身份证OCR.exe       (单文件独立运行主程序)" -ForegroundColor Green
Write-Host "   📄 dist\使用与激活指南.txt (闲鱼买家发货说明书)" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan
