# -*- coding: utf-8 -*-
"""
身份证OCR · 商业标准版
桌面客户端无控制台双击启动入口 (基于 Edge WebView2 / 本地内嵌轻量渲染)
"""

import sys
import os
import threading
import time
import socket

# 将根目录加入模块搜索路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from app import app
from auth_manager import auth_manager


def find_free_port(default_port=5000) -> int:
    """自动获取可用端口，防止端口冲突"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', default_port))
            return default_port
    except OSError:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]


def start_flask(port: int):
    """在后台子线程启动 Flask"""
    # 禁用 werkzeug 访问日志以提高性能和精简桌面体验
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


def main():
    port = find_free_port(5000)
    url = f"http://127.0.0.1:{port}"

    # 启动后台服务
    t = threading.Thread(target=start_flask, args=(port,), daemon=True)
    t.start()
    time.sleep(0.5)

    # 尝试优先启动原生桌面 WebView (无黑框、原生窗口体验)
    try:
        import webview
        window = webview.create_window(
            title="身份证OCR · 商业标准版",
            url=url,
            width=1240,
            height=820,
            min_size=(980, 680),
            background_color="#090d16"
        )
        webview.start()
        sys.exit(0)
    except ImportError:
        # 未安装 pywebview 时自动拉起系统默认浏览器
        import webbrowser
        print("=" * 55)
        print("  🪪 身份证OCR · 商业标准版 已启动")
        print(f"  桌面窗口地址: {url}")
        print(f"  本机机器码:   {auth_manager.machine_code}")
        print("=" * 55)
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            sys.exit(0)


if __name__ == "__main__":
    main()
