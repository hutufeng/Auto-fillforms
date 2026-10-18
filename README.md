# 🪪 身份证信息自动提取工具

基于 UMI-OCR + Flask 的身份证信息自动提取、Excel 导出、Word/Excel 模板填充工具。

## ✨ 功能

- **📷 身份证识别** — 上传正/反面图片，OCR 自动提取姓名、性别、民族、出生日期、年龄、身份证号码、住址、签发机关、有效期限
- **📁 批量处理** — 多张图片按文件名自动分组，批量识别
- **📄 模板填充** — 将识别结果自动填入 Word/Excel 模板（Jinja2 占位符）
- **📊 数据导出** — 导出到 Excel，支持追加模式
- **🕐 历史记录** — 查看、选择、导出历史识别数据

## 🛠️ 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | Python 3.11 + Flask |
| 前端 | HTML / CSS / JavaScript（暗色主题） |
| OCR | [UMI-OCR](https://github.com/hiroi-sora/Umi-OCR) HTTP API |
| Excel | openpyxl |
| Word | docxtpl (Jinja2) |

## 📦 安装

### 前置条件

- [Miniforge / Conda](https://github.com/conda-forge/miniforge)
- [UMI-OCR](https://github.com/hiroi-sora/Umi-OCR)（需启动 HTTP 服务，默认端口 1224）

### 安装步骤

```bash
# 1. 创建 conda 环境
conda create -n auto-fillforms python=3.11 -y
conda activate auto-fillforms

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动 UMI-OCR（确保 HTTP 服务在 127.0.0.1:1224 运行）

# 4. 启动应用
python app.py
```

访问 **http://127.0.0.1:5000**

## 📖 使用说明

### 单张识别

1. 打开 **身份证识别** 页面
2. 拖拽或点击上传身份证正面/反面图片
3. 点击 **开始识别**
4. 查看结果 → **填入模板** 或 **导出 Excel**

### 批量处理

上传多张图片，系统按文件名自动分组：

| 命名格式 | 示例 |
|---------|------|
| 姓名(数字) | `张三(1).jpg`, `张三(2).jpg` |
| 姓名_数字 | `张三_1.jpg`, `张三_2.jpg` |
| 姓名+数字 | `张三1.jpg`, `张三2.jpg` |
| 单张正反面 | `张三.jpg`（一张图含正反两面） |

同组最多取前 2 张，多余忽略。

### 模板制作

在 Word（`.docx`）或 Excel（`.xlsx`）模板中使用以下占位符：

```
{{姓名}}  {{性别}}  {{民族}}  {{出生日期}}  {{年龄}}
{{身份证号码}}  {{住址}}  {{签发机关}}  {{有效期限}}
```

批量填充时每人生成一份独立文件。

## 📁 项目结构

```
Auto-fillforms/
├── run_desktop.py         # 原生桌面程序快速启动入口
├── app_gui.py             # 现代化 CustomTkinter 响应式桌面主工作台
├── local_ocr.py           # 内置纯本地 RapidOCR 离线推理引擎
├── id_scanner.py          # 二代证边缘检测、倾斜纠偏、切片与A4扫描件生成
├── id_parser.py           # OCR 文本 → 结构化二代证 9 大字段解析
├── id_calculator.py       # 身份证号 → 生日/周岁/性别/校验码计算
├── id_cropper.py          # 免冠头像提取与系统剪贴板通道
├── excel_writer.py        # Excel 台账导出（实时追加）
├── template_filler.py     # Word/Excel 模板填充（文字+照片）
├── batch_processor.py     # 批量处理、文件名分组与多页/单页PDF解析
├── auth_manager.py        # 商业授权与在线换机解绑 SDK
├── build_portable.ps1     # 单文件便携版一键打包脚本
├── requirements.txt       # 纯本地依赖清单
├── user_templates/        # 套打模板目录
├── uploads/               # 临时解析缓存
└── output/                # 导出卡片、头像、A4扫描件与套打成果
```

## 💡 运行与使用

- **原生桌面版（推荐）**：直接运行 `start.bat` 或执行 `python run_desktop.py`
- **无需外部 OCR 软件**：内置 RapidOCR-ONNX 纯本地推理，断网脱机即开即用
- 身份证图片建议正拍、清晰，避免严重倾斜或反光
- 性别由身份证号第 17 位计算（奇=男，偶=女），不依赖 OCR 文本
- 身份证号末位 X 自动统一为大写
- 有效期支持「长期」格式

## 📄 License

MIT
