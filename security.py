# -*- coding: utf-8 -*-
"""安全与路径校验工具模块"""

from __future__ import annotations
import os
import re
import uuid


def safe_filename(filename: str) -> str:
    """安全获取文件名，保留中文字符，严格剔除路径遍历字符与非法字符"""
    if not filename:
        return f"file_{uuid.uuid4().hex[:8]}"
    # 仅保留纯文件名（剔除包含的任何目录路径）
    clean_name = os.path.basename(filename.replace("\\", "/"))
    # 去除首尾空白与危险点号
    clean_name = clean_name.strip().lstrip(".")
    # 过滤系统非法字符
    clean_name = re.sub(r'[\/:*?"<>|\r\n\t]', '_', clean_name)
    if not clean_name:
        clean_name = f"file_{uuid.uuid4().hex[:8]}"
    return clean_name


def is_safe_path(base_dir: str, target_path: str) -> bool:
    """确保目标路径严格在 base_dir 内部，防目录穿越攻击"""
    try:
        base_real = os.path.realpath(base_dir)
        target_real = os.path.realpath(target_path)
        return os.path.commonpath([base_real]) == os.path.commonpath([base_real, target_real])
    except Exception:
        return False
