# -*- coding: utf-8 -*-
<#
.SYNOPSIS
    身份证OCR · 商业单文件/绿色便携版一键打包脚本
.DESCRIPTION
    利用 PyInstaller 自动将 Python、Flask、本地 OCR 与前端资源封装为独立可执行文件
#>

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  🪪 身份证智能录入与扫描助手 · 绿色免安装版打包构建器" -ForegroundColor Green
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

# 打包命令 (纯原生极简单文件，无控制台黑框，零端口):
& $py -m PyInstaller `
    --noconfirm `
    --onefile `
    --windowed `
    --name "身份证智能录入与扫描助手" `
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

Write-Host "[4/4] 打包完成！生成配套使用指南..." -ForegroundColor Green

# 生成配套说明书 (客观无营销纯使用指南)
$GuideContent = @"
======================================================================
              身份证智能录入与扫描助手 · 使用指南
======================================================================

【软件概述】
本软件为纯绿色免安装版，无需配置 Python 环境，解压即用。
所有图像处理与 OCR 识别均在本地离线完成，无网络数据外发。

----------------------------------------------------------------------
一、首次运行与授权激活
----------------------------------------------------------------------
1. 双击运行【身份证智能录入与扫描助手.exe】。
2. 首次启动将弹出激活窗口，点击【一键复制机器码】。
3. 将机器码发送给授权管理员，获取 16 位激活卡密。
4. 粘贴卡密并点击【立即联网验证激活】（仅激活时需连接网络验证 1 秒）。
5. 激活完成后即可完全离线使用。

----------------------------------------------------------------------
二、单张识别与功能操作
----------------------------------------------------------------------
1. 导入图片：
   - 分别选择身份证正面与反面图片；
   - 或直接上传一张包含正反两面的合图。
2. 识别提取：
   - 【快速提取 (纯 OCR)】：快速提取文字信息到右侧表单；
   - 【完整识别 (含切片)】：自动纠偏倾斜、切取二代证国标圆角卡片，
     并提取免冠证件照头像。
3. 头像与卡片使用：
   - 点击【复制头像】可直接在微信、Word 或其他软件中 Ctrl+V 粘贴；
   - 点击【另存头像】可将证件照保存为独立 JPG 文件。
4. 导出 A4 规范扫描件：
   - 点击【导出此人 A4 扫描件】；
   - 支持【彩色高保真】或【黑白复印机】质感；
   - 可按需勾选【防盗用水印】并设置防挪用提示文字；
   - 点击即可导出 300DPI 标准 PDF 或 JPG。

----------------------------------------------------------------------
三、批量处理与自动配对
----------------------------------------------------------------------
1. 切换至【批量表格生成】标签页。
2. 点击【选择图片文件夹】导入包含多张身份证照片的目录。
3. 推荐命名规则（自动按人名配对）：
   - 张三1.jpg、张三2.jpg
   - 李四(1).jpg、李四(2).jpg
   - 王五_正.jpg、王五_反.jpg
   - 赵六.jpg（单图含正反两面）
4. 文件列表支持按住 Ctrl 或 Shift 鼠标多选，点击【移除选中项】
   可快速剔除误选的文件。
5. 点击【开始批量识别】，完成后支持：
   - 【导出 Excel 表格】：一键导出包含全员信息的汇总台账；
   - 【批量导出 A4 扫描件】：可选择每人一份独立文件，或合并为单份
     全员多页汇总 PDF。

----------------------------------------------------------------------
四、Word / Excel 模板智能套打
----------------------------------------------------------------------
1. 在自定义 Word (.docx) 模板中设置占位符：
   - 文字字段：{{姓名}}  {{性别}}  {{民族}}  {{出生日期}}  {{年龄}}
               {{身份证号码}}  {{住址}}  {{签发机关}}  {{有效期限}}
   - 图片字段：{{avatar}} (自动插入免冠头像)
               {{card_front}} (自动插入正面卡片)
               {{card_back}} (自动插入反面卡片)
2. 在软件中点击【选择 Word/Excel 模板】导入模板。
3. 点击【填充并导出】，系统将自动为每人生成一份独立套打文档。

----------------------------------------------------------------------
五、注意事项
----------------------------------------------------------------------
1. 照片建议平放清晰拍摄，避免反光或强烈阴影遮挡关键文字。
2. 如需更换电脑运行，请使用软件内置的【换机解绑】功能。
======================================================================
"@

$GuidePath = ".\dist\使用指南.txt"
[System.IO.File]::WriteAllText($GuidePath, $GuideContent, [System.Text.Encoding]::UTF8)

Write-Host "`n✅ 构建成果已存放于 dist/ 目录：" -ForegroundColor Cyan
Write-Host "   📁 dist\身份证智能录入与扫描助手.exe (单文件独立运行主程序)" -ForegroundColor Green
Write-Host "   📄 dist\使用指南.txt                (用户操作指南)" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan
