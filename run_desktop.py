# -*- coding: utf-8 -*-
"""
身份证OCR · 商业标准版
纯原生轻量桌面程序启动入口 (零 HTTP 端口 / 零网络占用 / 毫秒级冷启动)
"""

import sys
import os

# 将根目录加入模块搜索路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from app_gui import AppGUI


def main():
    app = AppGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
