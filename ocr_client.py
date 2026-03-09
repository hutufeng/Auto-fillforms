# -*- coding: utf-8 -*-
"""UMI-OCR HTTP 调用模块"""

import base64
import requests
from config import OCR_API_URL, OCR_TIMEOUT


def check_ocr_service() -> bool:
    """检测 UMI-OCR 服务是否可用"""
    try:
        resp = requests.get(f"{OCR_API_URL}/get_options", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def ocr_image(image_path: str) -> list[str]:
    """
    调用 UMI-OCR 识别图片，返回文本行列表。
    
    Args:
        image_path: 图片文件绝对路径
    
    Returns:
        识别到的文本行列表，识别失败返回空列表
    """
    try:
        with open(image_path, "rb") as f:
            img_base64 = base64.b64encode(f.read()).decode("utf-8")

        payload = {
            "base64": img_base64,
            "options": {}
        }

        resp = requests.post(
            OCR_API_URL,
            json=payload,
            timeout=OCR_TIMEOUT
        )

        if resp.status_code != 200:
            print(f"[OCR] HTTP 错误: {resp.status_code}")
            return []

        result = resp.json()

        # UMI-OCR 返回格式：{"code": 100, "data": [{"text": "...", "box": [...], "score": ...}, ...]}
        if result.get("code") == 100 and result.get("data"):
            lines = [item["text"] for item in result["data"] if "text" in item]
            return lines
        elif result.get("code") == 101:
            # 101 = 无文字
            print("[OCR] 未识别到文字")
            return []
        else:
            print(f"[OCR] 识别异常: {result}")
            return []

    except FileNotFoundError:
        print(f"[OCR] 文件不存在: {image_path}")
        return []
    except requests.exceptions.ConnectionError:
        print("[OCR] 无法连接 UMI-OCR 服务，请确认已启动")
        return []
    except Exception as e:
        print(f"[OCR] 异常: {e}")
        return []
