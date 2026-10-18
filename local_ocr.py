# -*- coding: utf-8 -*-
"""
纯本地离线 OCR 驱动模块 (RapidOCR ONNX 引擎)
彻底移除外部 UMI-OCR 依赖，无需网络与外部进程，开箱即用纯离线运行
"""

from __future__ import annotations
import os

_rapid_ocr_engine = None

def _get_engine():
    global _rapid_ocr_engine
    if _rapid_ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _rapid_ocr_engine = RapidOCR()
        except ImportError:
            _rapid_ocr_engine = None
    return _rapid_ocr_engine


def is_offline_engine_available() -> bool:
    """检查内置本地离线 OCR 是否可用"""
    return _get_engine() is not None


def check_ocr_service() -> bool:
    """对外统一健康检测"""
    return is_offline_engine_available()


def get_ocr_engine_name() -> str:
    """获取当前引擎名称"""
    if is_offline_engine_available():
        return "内置本地引擎 (RapidOCR)"
    return "本地引擎未安装 (需 rapidocr-onnxruntime)"


def ocr_image(image_path: str) -> list[str]:
    """
    纯本地 OCR 识别入口
    返回识别出的文本行列表
    """
    if not os.path.exists(image_path):
        return []

    engine = _get_engine()
    if engine is None:
        print("[OCR] 错误: 本地 RapidOCR 引擎未安装")
        return []

    try:
        result, elapse = engine(image_path)
        if not result:
            return []
        # RapidOCR 返回格式: [[box, text, score], ...]
        lines = [item[1].strip() for item in result if len(item) > 1 and item[1]]
        return lines
    except Exception as e:
        print(f"[OCR] 本地识别异常: {e}")
        return []
