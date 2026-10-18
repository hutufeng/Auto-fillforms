# -*- coding: utf-8 -*-
"""
身份证智能裁剪与系统剪贴板支持模块
基于 id_scanner 核心进行精准正立卡片提取与免冠头像切片
"""

from __future__ import annotations
import os
import io
import hashlib
from PIL import Image
from id_scanner import correct_and_crop_card, crop_avatar_from_standard_card


def crop_avatar(front_image_path: str, output_path: str | None = None) -> Image.Image | None:
    """
    智能矫正正面身份证并精准切取二代证头像
    """
    if not front_image_path or not os.path.exists(front_image_path):
        return None
    try:
        # 1. 先进行透视校正与摆正
        card_front = correct_and_crop_card(front_image_path, mode="color")
        if card_front is None:
            return None

        # 2. 从标准正面上切取国标尺寸免冠头像
        avatar = crop_avatar_from_standard_card(card_front)
        if avatar and output_path:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            avatar.save(output_path, "JPEG", quality=95, dpi=(300, 300))
        return avatar
    except Exception as e:
        print(f"[Cropper] 精准头像切片异常: {e}")
        return None


def copy_image_to_clipboard(image: Image.Image) -> bool:
    """将 PIL 图像复制到 Windows 系统剪贴板"""
    try:
        import win32clipboard
        output = io.BytesIO()
        image.convert("RGB").save(output, "BMP")
        data = output.getvalue()[14:]
        output.close()

        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
        win32clipboard.CloseClipboard()
        return True
    except Exception:
        try:
            import base64
            import subprocess
            buf = io.BytesIO()
            image.convert("RGB").save(buf, "PNG")
            b64_str = base64.b64encode(buf.getvalue()).decode("ascii")
            buf.close()

            ps_script = (
                f"$b=[System.Convert]::FromBase64String('{b64_str}');"
                "$ms=New-Object System.IO.MemoryStream($b,0,$b.Length);"
                "$img=[System.Drawing.Image]::FromStream($ms);"
                "Add-Type -AssemblyName System.Windows.Forms;"
                "[System.Windows.Forms.Clipboard]::SetImage($img);"
                "$img.Dispose();$ms.Dispose()"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, check=True)
            return True
        except Exception as e:
            print(f"[Cropper] 复制剪贴板失败: {e}")
            return False
