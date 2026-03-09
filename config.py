# -*- coding: utf-8 -*-
"""全局配置"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# UMI-OCR 服务
OCR_API_URL = "http://127.0.0.1:1224/api/ocr"
OCR_TIMEOUT = 30  # 秒

# 文件目录
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
USER_TEMPLATES_DIR = os.path.join(BASE_DIR, "user_templates")
SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}

# 确保目录存在
for d in [UPLOAD_DIR, OUTPUT_DIR, USER_TEMPLATES_DIR]:
    os.makedirs(d, exist_ok=True)
