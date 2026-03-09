# -*- coding: utf-8 -*-
"""批量处理模块：文件名分组 + 批量 OCR 识别"""

import os
import re
from config import SUPPORTED_IMAGE_EXTS
from ocr_client import ocr_image
from id_parser import parse_single_image, parse_id_card, is_front_side, is_back_side


def _extract_base_name(filename: str) -> str:
    """
    从文件名提取基础名（用于分组）。
    
    规则：去掉扩展名后，去掉以下后缀模式：
    - (数字) 或 （数字）：张三(1) → 张三
    - _数字：张三_1 → 张三
    - 末尾纯数字：张三1 → 张三
    """
    # 去掉扩展名
    name = os.path.splitext(filename)[0]

    # 去掉 (数字) 或 （数字） 后缀
    name = re.sub(r'[(\（]\d+[)\）]$', '', name)

    # 去掉 _数字 后缀
    name = re.sub(r'_\d+$', '', name)

    # 去掉末尾纯数字（但保留至少一个非数字字符）
    name = re.sub(r'(\D)\d+$', r'\1', name)

    return name.strip()


def group_files(image_dir: str) -> dict[str, list[str]]:
    """
    扫描目录，按文件名基础名分组。
    
    Args:
        image_dir: 图片目录路径
    
    Returns:
        {基础名: [文件绝对路径列表]}，每组最多2个文件
    """
    groups = {}

    if not os.path.isdir(image_dir):
        return groups

    for filename in sorted(os.listdir(image_dir)):
        ext = os.path.splitext(filename)[1].lower()
        if ext not in SUPPORTED_IMAGE_EXTS:
            continue

        base_name = _extract_base_name(filename)
        filepath = os.path.join(image_dir, filename)

        if base_name not in groups:
            groups[base_name] = []

        # 每组最多取前2张，多余忽略
        if len(groups[base_name]) < 2:
            groups[base_name].append(filepath)

    return groups


def process_single_group(file_paths: list[str]) -> dict:
    """
    处理单组文件（1-2张图片），返回完整身份证数据。
    """
    front_lines = None
    back_lines = None
    warnings = []

    if len(file_paths) == 1:
        # 单张图片：可能是正面、反面或正反面合图
        lines = ocr_image(file_paths[0])
        if not lines:
            return {"_error": f"OCR 识别失败: {file_paths[0]}", "_warnings": ["OCR 未返回文本"]}

        data, side = parse_single_image(lines)
        if side == "both":
            data["_raw_ocr_front"] = lines
            return {**data, "_warnings": ["单图包含正反面，已自动拆分"]}
        elif side == "front":
            warnings.append("仅识别到正面，反面信息缺失")
            data["_raw_ocr_front"] = lines
            return {**data, "_warnings": warnings}
        elif side == "back":
            warnings.append("仅识别到反面，正面信息缺失")
            data["_raw_ocr_back"] = lines
            return {**data, "_warnings": warnings}
        else:
            return {"_error": "无法识别为身份证", "_warnings": ["未检测到身份证关键词"]}

    else:
        # 两张图片：分别识别，自动判断正反面
        for fp in file_paths:
            lines = ocr_image(fp)
            if not lines:
                warnings.append(f"OCR 识别失败: {os.path.basename(fp)}")
                continue

            if is_front_side(lines) and front_lines is None:
                front_lines = lines
            elif is_back_side(lines) and back_lines is None:
                back_lines = lines
            elif front_lines is None:
                # 默认当作正面
                front_lines = lines
            elif back_lines is None:
                back_lines = lines

        if front_lines is None and back_lines is None:
            return {"_error": "两张图片均识别失败", "_warnings": warnings}

        if front_lines:
            data = parse_id_card(front_lines, back_lines)
        else:
            data = parse_id_card([], back_lines)
            warnings.append("正面识别失败")

        if back_lines is None:
            warnings.append("反面信息缺失")

        data["_warnings"] = warnings
        # 保留原始 OCR 文本行
        if front_lines:
            data["_raw_ocr_front"] = front_lines
        if back_lines:
            data["_raw_ocr_back"] = back_lines
        return data


def process_batch(image_dir: str) -> list[dict]:
    """
    批量处理整个目录的身份证图片。
    
    Returns:
        每个人的识别结果列表，每条含 _group_name 和 _warnings 字段
    """
    groups = group_files(image_dir)
    results = []

    for group_name, file_paths in groups.items():
        data = process_single_group(file_paths)
        data["_group_name"] = group_name
        data["_files"] = [os.path.basename(f) for f in file_paths]
        results.append(data)

    return results
