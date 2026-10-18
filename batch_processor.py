# -*- coding: utf-8 -*-
"""
批量处理模块：文件名智能分组 + 本地 OCR 识别 + 身份证卡面精准矫正与专属头像切片
"""

from __future__ import annotations
import os
import re
import hashlib
from config import SUPPORTED_IMAGE_EXTS, OUTPUT_DIR, UPLOAD_DIR
from local_ocr import ocr_image
from id_parser import parse_single_image, parse_id_card, is_front_side, is_back_side
from id_scanner import correct_and_crop_card, crop_avatar_from_standard_card, crop_both_sides_from_single_image


def render_pdf_to_images(pdf_path: str) -> list[str]:
    """使用 pymupdf 极速将多页或单页 PDF 渲染为高清图片缓存 (200 DPI)"""
    if not os.path.exists(pdf_path):
        return []
    doc = None
    try:
        import pymupdf
        doc = pymupdf.open(pdf_path)
        stem = re.sub(r'[\\/*?:\[\]]', '', os.path.splitext(os.path.basename(pdf_path))[0])
        cache_dir = os.path.join(UPLOAD_DIR, "pdf_cache", stem)
        os.makedirs(cache_dir, exist_ok=True)

        pages = []
        for i in range(len(doc)):
            page_png = os.path.join(cache_dir, f"page_{i+1}.png")
            if not os.path.exists(page_png):
                pix = doc[i].get_pixmap(dpi=200)
                pix.save(page_png)
            pages.append(page_png)
        return pages
    except Exception as e:
        print(f"[PDF] 渲染 PDF 页面异常 ({pdf_path}): {e}")
        return []
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


def _extract_base_name(filename: str) -> str:
    """从文件名提取基础名（用于人员分组）"""
    name = os.path.splitext(filename)[0]
    # 去除 (1) 或 （1）
    name = re.sub(r'[(\（]\d+[)\）]$', '', name)
    # 去除 _1, _2, -1, -2
    name = re.sub(r'[_\-]\d+$', '', name)
    # 去除“正面”、“反面”、“国徽面”、“人像面”
    name = re.sub(r'[_\-]?(正面|反面|人像面|国徽面|A面|B面)$', '', name, flags=re.IGNORECASE)
    # 去除末尾纯数字（但保留至少一个字符）
    name = re.sub(r'(\D)\d+$', r'\1', name)
    cleaned = name.strip()
    return cleaned if cleaned else os.path.splitext(filename)[0]


def group_files(image_dir: str) -> dict[str, list[str]]:
    """
    扫描目录并智能分组（支持常规图片与 PDF 混合解析）：
    - 常规图片按文件名智能对齐（每组 1-2 张）
    - PDF 自动解构展开并自适应正反面配对
    """
    groups = {}
    if not os.path.isdir(image_dir):
        return groups

    all_files = sorted(os.listdir(image_dir))
    file_paths = [os.path.abspath(os.path.join(image_dir, f)) for f in all_files]
    return auto_group_items(file_paths)


def auto_group_items(item_paths: list[str]) -> dict[str, list[str]]:
    """
    统一智能分组引擎：处理图片与 PDF 混合列表
    """
    groups = {}
    from config import SUPPORTED_IMAGE_EXTS

    for item_path in item_paths:
        if not os.path.exists(item_path):
            continue

        ext = os.path.splitext(item_path)[1].lower()

        # 1. 处理 PDF 文档
        if ext == ".pdf":
            pages = render_pdf_to_images(item_path)
            if not pages:
                continue

            pdf_stem = os.path.splitext(os.path.basename(item_path))[0]
            if len(pages) == 1:
                # 单页 PDF
                groups[f"{pdf_stem}"] = [pages[0]]
            else:
                # 多页 PDF：自适应判定排版模式
                p1_lines = ocr_image(pages[0])
                _, p1_side = parse_single_image(p1_lines)

                if p1_side == "both":
                    # 模式 A：每页一人 (一页内同时包含正反面)
                    for idx, p_img in enumerate(pages, 1):
                        groups[f"{pdf_stem}_第{idx}页"] = [p_img]
                elif p1_side == "front" and len(pages) >= 2:
                    # 抽检第 2 页
                    p2_lines = ocr_image(pages[1])
                    _, p2_side = parse_single_image(p2_lines)
                    if p2_side == "back":
                        # 模式 B：两页一人 (奇数页正面，偶数页反面)
                        p_idx = 1
                        i = 0
                        while i < len(pages):
                            if i + 1 < len(pages):
                                groups[f"{pdf_stem}_人员{p_idx}"] = [pages[i], pages[i+1]]
                                i += 2
                            else:
                                groups[f"{pdf_stem}_人员{p_idx}_单页"] = [pages[i]]
                                i += 1
                            p_idx += 1
                    else:
                        # 连续正面汇总
                        for idx, p_img in enumerate(pages, 1):
                            groups[f"{pdf_stem}_第{idx}页"] = [p_img]
                else:
                    # 默认每页独立成组
                    for idx, p_img in enumerate(pages, 1):
                        groups[f"{pdf_stem}_第{idx}页"] = [p_img]

        # 2. 处理常规图片
        elif ext in SUPPORTED_IMAGE_EXTS:
            filename = os.path.basename(item_path)
            base_name = _extract_base_name(filename)

            target_group = base_name
            sub_idx = 1
            while target_group in groups and len(groups[target_group]) >= 2:
                sub_idx += 1
                target_group = f"{base_name}_{sub_idx}"

            if target_group not in groups:
                groups[target_group] = []
            groups[target_group].append(item_path)

    return groups



def process_single_group(
    file_paths: list[str],
    with_crop: bool = False
) -> dict:
    """
    处理单组身份证图片（1-2张）：
    with_crop=False: 纯 OCR 极速提取模式 (秒级完成，不执行任何卡面切片)
    with_crop=True:  完整识别与切片模式 (OCR + 卡面智能纠偏 + 正反面标准圆角切片 + 免冠头像切片)
    """
    front_lines = None
    back_lines = None
    warnings = []
    side = ""

    # 为本组生成绝对唯一的 hash id
    raw_key = "_".join([os.path.basename(p) for p in file_paths])
    group_uid = hashlib.md5(raw_key.encode("utf-8", errors="ignore")).hexdigest()[:8]

    cards_dir = os.path.join(OUTPUT_DIR, "cards")
    avatars_dir = os.path.join(OUTPUT_DIR, "avatars")
    if with_crop:
        os.makedirs(cards_dir, exist_ok=True)
        os.makedirs(avatars_dir, exist_ok=True)

    front_raw_path = None
    back_raw_path = None

    if len(file_paths) == 1:
        fp = file_paths[0]
        lines = ocr_image(fp)
        if not lines:
            return {"_error": f"OCR 识别失败: {os.path.basename(fp)}", "_warnings": ["OCR 未返回文本"]}

        data, side = parse_single_image(lines)

        if side in ("both", "front"):
            front_raw_path = fp
        if side in ("both", "back"):
            back_raw_path = fp

        if side == "both":
            data["_raw_ocr_front"] = lines
            warnings.append("单图包含正反面，已自动拆分")
        elif side == "front":
            warnings.append("仅识别到正面，反面信息缺失")
            data["_raw_ocr_front"] = lines
        elif side == "back":
            warnings.append("仅识别到反面，正面信息缺失")
            data["_raw_ocr_back"] = lines
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
                front_raw_path = fp
            elif is_back_side(lines) and back_lines is None:
                back_lines = lines
                back_raw_path = fp
            elif front_lines is None:
                front_lines = lines
                front_raw_path = fp
            elif back_lines is None:
                back_lines = lines
                back_raw_path = fp

        if front_lines is None and back_lines is None:
            return {"_error": "两张图片均识别失败", "_warnings": warnings}

        if front_lines:
            data = parse_id_card(front_lines, back_lines)
            data["_raw_ocr_front"] = front_lines
        else:
            data = parse_id_card([], back_lines)
            warnings.append("正面识别失败")

        if back_lines is None:
            warnings.append("反面信息缺失")
        else:
            data["_raw_ocr_back"] = back_lines

    # ====== 图像切片处理 (仅在 with_crop=True 时执行) ======
    name_str = re.sub(r'[\\/*?:\[\]]', '', str(data.get("name") or "未命名"))
    clean_front_path = ""
    clean_back_path = ""
    avatar_clean_path = ""

    if with_crop:
        # 模式 A：单图同时包含正反两面 (一图双面)
        if len(file_paths) == 1 and side == "both" and front_raw_path and os.path.exists(front_raw_path):
            card_front_img, card_back_img = crop_both_sides_from_single_image(front_raw_path, mode="color")
            if card_front_img:
                clean_front_path = os.path.join(cards_dir, f"front_{name_str}_{group_uid}.png")
                card_front_img.save(clean_front_path, "PNG", dpi=(300, 300))
                # 像素级免冠头像切片
                av_img = crop_avatar_from_standard_card(card_front_img)
                if av_img:
                    avatar_clean_path = os.path.join(avatars_dir, f"avatar_{name_str}_{group_uid}.jpg")
                    av_img.convert("RGB").save(avatar_clean_path, "JPEG", quality=95, dpi=(300, 300))
            if card_back_img:
                clean_back_path = os.path.join(cards_dir, f"back_{name_str}_{group_uid}.png")
                card_back_img.save(clean_back_path, "PNG", dpi=(300, 300))
        else:
            # 模式 B：常规单面或双图两面独立切片
            if front_raw_path and os.path.exists(front_raw_path):
                card_front_img = correct_and_crop_card(front_raw_path, mode="color")
                if card_front_img:
                    clean_front_path = os.path.join(cards_dir, f"front_{name_str}_{group_uid}.png")
                    card_front_img.save(clean_front_path, "PNG", dpi=(300, 300))
                    # 像素级免冠头像切片
                    av_img = crop_avatar_from_standard_card(card_front_img)
                    if av_img:
                        avatar_clean_path = os.path.join(avatars_dir, f"avatar_{name_str}_{group_uid}.jpg")
                        av_img.convert("RGB").save(avatar_clean_path, "JPEG", quality=95, dpi=(300, 300))

            if back_raw_path and os.path.exists(back_raw_path):
                card_back_img = correct_and_crop_card(back_raw_path, mode="color")
                if card_back_img:
                    clean_back_path = os.path.join(cards_dir, f"back_{name_str}_{group_uid}.png")
                    card_back_img.save(clean_back_path, "PNG", dpi=(300, 300))

    data["front_image_path"] = clean_front_path or (front_raw_path or "")
    data["back_image_path"] = clean_back_path or (back_raw_path or "")
    data["avatar_path"] = avatar_clean_path
    data["_has_cropped"] = bool(clean_front_path or avatar_clean_path or clean_back_path)
    data["_group_uid"] = group_uid
    data["_warnings"] = warnings

    return data



def process_batch(image_dir: str) -> list[dict]:
    """批量处理整个目录的身份证图片"""
    groups = group_files(image_dir)
    results = []

    for group_name, file_paths in groups.items():
        data = process_single_group(file_paths)
        data["_group_name"] = group_name
        data["_files"] = [os.path.basename(f) for f in file_paths]
        results.append(data)

    return results
