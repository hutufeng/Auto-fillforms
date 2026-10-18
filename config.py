# -*- coding: utf-8 -*-
"""全局配置"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 运行参数
MAX_HISTORY_SIZE = int(os.getenv("MAX_HISTORY_SIZE", "200"))

# 文件目录
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
USER_TEMPLATES_DIR = os.path.join(BASE_DIR, "user_templates")
SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}

# 确保目录存在
for d in [UPLOAD_DIR, OUTPUT_DIR, USER_TEMPLATES_DIR]:
    os.makedirs(d, exist_ok=True)
