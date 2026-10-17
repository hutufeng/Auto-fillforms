# -*- coding: utf-8 -*-
"""
内置离线 OCR 引擎驱动模块
优先使用内置 RapidOCR (ONNX 离线模型，无需外部服务，开箱即用)
若未安装则自动回退至 UMI-OCR HTTP 服务
"""

from __future__ import annotations
import os
import base64
import requests
from config import OCR_API_URL, OCR_TIMEOUT

# 尝试导入 RapidOCR
_rapid_ocr_engine = None
try:
    from rapidocr_onnxruntime import RapidOCR
    _rapid_ocr_engine = RapidOCR()
    print("[OCR] 成功初始化内置离线 RapidOCR 引擎")
except Exception as e:
    _rapid_ocr_engine = None


def is_offline_engine_available() -> bool:
    """是否可用内置离线 OCR 引擎"""
    return _rapid_ocr_engine is not None


def check_ocr_service() -> bool:
    """检查 OCR 引擎是否就绪"""
    if _rapid_ocr_engine is not None:
        return True
    try:
        resp = requests.get(f"{OCR_API_URL}/get_options", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def get_ocr_engine_name() -> str:
    """获取当前使用的 OCR 引擎名称"""
    if _rapid_ocr_engine is not None:
        return "内置离线引擎 (RapidOCR)"
    return "外部服务 (UMI-OCR HTTP)"


def ocr_image(image_path: str) -> list[str]:
    """
    统一的 OCR 图片识别入口
    返回识别出的文本行列表
    """
    if not os.path.exists(image_path):
        return []

    # 1. 优先使用内置离线引擎
    if _rapid_ocr_engine is not None:
        try:
            result, elapse = _rapid_ocr_engine(image_path)
            if not result:
                return []
            # RapidOCR 返回: [[box, text, score], ...]
            lines = [item[1] for item in result if len(item) > 1 and item[1]]
            return lines
        except Exception as e:
            print(f"[OCR] 内置引擎识别异常: {e}")

    # 2. 回退到 UMI-OCR HTTP 服务
    try:
        with open(image_path, "rb") as f:
            img_base64 = base64.b64encode(f.read()).decode("utf-8")

        payload = {"base64": img_base64, "options": {}}
        resp = requests.post(OCR_API_URL, json=payload, timeout=OCR_TIMEOUT)
        if resp.status_code == 200:
            res_data = resp.json()
            if res_data.get("code") == 100 and res_data.get("data"):
                return [item["text"] for item in res_data["data"] if "text" in item]
    except Exception as e:
        print(f"[OCR] 外部服务调用异常: {e}")

    return []
