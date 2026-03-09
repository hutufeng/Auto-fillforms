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
├── app.py                 # Flask 主应用
├── config.py              # 全局配置
├── ocr_client.py          # UMI-OCR HTTP 调用
├── id_parser.py           # OCR 文本 → 结构化数据
├── id_calculator.py       # 身份证号 → 生日/年龄/性别
├── excel_writer.py        # Excel 写入（追加模式）
├── template_filler.py     # Word/Excel 模板填充
├── batch_processor.py     # 批量处理 + 文件名分组
├── requirements.txt
├── static/css/style.css   # 暗色主题样式
├── static/js/app.js       # 前端交互逻辑
├── templates/index.html   # 单页 HTML
├── user_templates/        # 用户上传的模板
├── uploads/               # 上传图片（临时）
└── output/                # 导出文件
```

## ⚠️ 注意事项

- 需先启动 UMI-OCR 并确保 HTTP 服务可用
- 身份证图片建议正拍、清晰，避免严重倾斜或反光
- 性别由身份证号第 17 位计算（奇=男，偶=女），不依赖 OCR 文本
- 身份证号末位 X 自动统一为大写
- 有效期支持「长期」格式

## 📄 License

MIT
