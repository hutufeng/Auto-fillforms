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

# 打包命令 (纯原生极简单文件，无控制台黑框，零端口，体积仅约 15MB~20MB):
& $py -m PyInstaller `
    --noconfirm `
    --onefile `
    --windowed `
    --name "身份证OCR" `
    --icon "assets\icon.ico" `
    --add-data "assets;assets" `
    --hidden-import "cryptography" `
    --hidden-import "openpyxl" `
    --hidden-import "docxtpl" `
    --hidden-import "customtkinter" `
    --hidden-import "cv2" `
    --hidden-import "pymupdf" `
    --hidden-import "fitz" `
    --collect-all "customtkinter" `
    --collect-all "rapidocr_onnxruntime" `
    app_gui.py

Write-Host "[4/4] 打包完成！生成闲鱼发货便携包与买家指南..." -ForegroundColor Green

# 生成买家配套说明书
$GuideContent = @"
======================================================================
     🪪 身份证智能识别与 A4 扫描件管理系统 · 使用与激活指南
======================================================================

感谢您购买本软件！本软件为纯绿色免安装单文件版，无需安装 Python 或任何复杂环境，
解压后双击即可运行。数据完全在您本地离线处理，100% 保护隐私安全。

----------------------------------------------------------------------
一、首次使用与激活步骤（仅需 1 分钟）
----------------------------------------------------------------------
1. 双击运行当前目录下的【身份证OCR.exe】。
2. 首次启动软件会自动弹出授权窗口，点击【一键复制机器码】。
3. 将机器码发送给闲鱼卖家，卖家核验后将为您发放 16 位专属激活卡密。
4. 将卡密粘贴到软件输入框中，点击【立即联网验证激活】，即可永久解锁核心功能！

----------------------------------------------------------------------
二、主要核心功能使用指引
----------------------------------------------------------------------
1. 单张与一图双面识别：
   - 支持分别选择正反两面，或直接上传一张包含正反两面的合图照片；
   - 点击【完整识别】：自动纠偏倾斜、切取二代证国标圆角卡片；
   - 点击【复制头像】：秒级提取二代证免冠照片，直接 Ctrl+V 粘贴使用；
   - 点击【导出此人 A4 扫描件】：可选择彩色高清或黑白复印质感，并支持自定义防盗防挪用水印。

2. 批量处理与全员汇总：
   - 切换到【批量表格生成】标签，导入文件夹；
   - 支持按住 Ctrl/Shift 鼠标多选图片，随时一键移除误选文件；
   - 点击【开始批量识别】，完成后一键导出汇总 Excel 台账或批量生成全员 A4 扫描件。

3. Word / Excel 模板智能套打：
   - 在模板中使用 {{姓名}}、{{身份证号码}}、{{avatar}} (自动插入头像) 等占位符，一键批量填充生成独立文档。

祝您使用愉快！如有疑问请随时联系闲鱼卖家。
======================================================================
"@

$GuidePath = ".\dist\使用与激活指南.txt"
[System.IO.File]::WriteAllText($GuidePath, $GuideContent, [System.Text.Encoding]::UTF8)

Write-Host "`n✅ 构建成果已存放于 dist/ 目录：" -ForegroundColor Cyan
Write-Host "   📁 dist\身份证OCR.exe       (单文件独立运行主程序)" -ForegroundColor Green
Write-Host "   📄 dist\使用与激活指南.txt (闲鱼买家发货说明书)" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan
