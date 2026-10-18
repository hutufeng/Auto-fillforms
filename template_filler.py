# -*- coding: utf-8 -*-
"""
模板填充模块：支持 Word (docxtpl) 和 Excel (openpyxl) 模板
支持独立文件套打、邮件合并式单文件汇总套打，以及图片占位符自动嵌入
"""

from __future__ import annotations
import os
import re
import tempfile
from docxtpl import DocxTemplate, InlineImage
from docx.shared import Mm
from openpyxl import load_workbook


# 占位符 → 数据字典 key 的映射
PLACEHOLDER_MAP = {
    "姓名": "name",
    "性别": "gender",
    "民族": "ethnicity",
    "出生日期": "birthday",
    "年龄": "age",
    "身份证号码": "id_number",
    "住址": "address",
    "签发机关": "authority",
    "有效期限": "validity",
}


from PIL import Image

def _make_safe_inline_image(doc: DocxTemplate, img_path: str | None, target_width_mm: float, default_ratio: float = 0.63):
    """
    安全载入图片并强制规范 DPI 与同时设定精确 (width, height)，
    彻底规避手机相机或某些修图软件中 DPI 为 (0,0) 引发 python-docx 内部 division by zero 崩溃
    """
    if not img_path or not os.path.exists(img_path):
        return ""
    try:
        with Image.open(img_path) as im:
            w, h = im.size
            if w <= 0 or h <= 0:
                return ""
            ratio = h / w if w > 0 else default_ratio
            target_height_mm = target_width_mm * ratio

            # 检测并修复 DPI，透明 PNG 保持 PNG
            dpi = im.info.get("dpi")
            safe_file_path = img_path
            is_png = img_path.lower().endswith(".png") or im.mode == "RGBA"

            if not dpi or dpi[0] <= 0 or dpi[1] <= 0:
                cache_dir = os.path.join(tempfile.gettempdir(), "safe_ocr_imgs")
                os.makedirs(cache_dir, exist_ok=True)
                if is_png:
                    safe_file_path = os.path.join(cache_dir, f"safe_{os.path.basename(img_path)}.png")
                    im.save(safe_file_path, "PNG", dpi=(300, 300))
                else:
                    safe_file_path = os.path.join(cache_dir, f"safe_{os.path.basename(img_path)}.jpg")
                    im.convert("RGB").save(safe_file_path, "JPEG", quality=95, dpi=(300, 300))

            # 同时传入明确的 width 和 height，跳过 docx 的自动计算分支
            return InlineImage(doc, safe_file_path, width=Mm(target_width_mm), height=Mm(target_height_mm))
    except Exception as e:
        print(f"[Template] 制作安全图片失败 ({img_path}): {e}")
        return ""


def _ensure_rounded_card_image(img_path: str | None, card_type: str = "front", name_hint: str = "") -> str:
    """
    确保返回的正面/反面卡片是采用与 PDF 扫描件完全一致的
    背景剥离、倾斜矫正、正立对齐以及标准二代证平滑圆角 PNG 图片
    """
    if not img_path or not os.path.exists(img_path):
        return ""

    base_name = os.path.basename(img_path).lower()
    # 若已经是带有平滑圆角的 PNG 卡片则直接复用
    if (base_name.startswith("front_") or base_name.startswith("back_")) and base_name.endswith(".png"):
        return img_path

    try:
        from id_scanner import correct_and_crop_card
        import hashlib
        cards_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "cards")
        os.makedirs(cards_dir, exist_ok=True)

        card_img = correct_and_crop_card(img_path, mode="color")
        if card_img:
            name_clean = re.sub(r'[\\/*?:\[\]]', '', str(name_hint or "card"))
            h_uid = hashlib.md5(img_path.encode("utf-8", errors="ignore")).hexdigest()[:6]
            clean_path = os.path.join(cards_dir, f"{card_type}_{name_clean}_{h_uid}.png")
            card_img.save(clean_path, "PNG", dpi=(300, 300))
            return clean_path
    except Exception as e:
        print(f"[Template] 自动矫正圆角卡片异常 ({img_path}): {e}")

    return img_path


def _ensure_avatar_image(avatar_path: str | None, front_card_path: str | None, name_hint: str = "") -> str:
    """确保免冠头像存在，若缺失则自动从标准正面卡面精准切取"""
    if avatar_path and os.path.exists(avatar_path):
        return avatar_path
    if not front_card_path or not os.path.exists(front_card_path):
        return ""
    try:
        from id_scanner import crop_avatar_from_standard_card
        import hashlib
        with Image.open(front_card_path) as im:
            av = crop_avatar_from_standard_card(im)
            if av:
                avatars_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "avatars")
                os.makedirs(avatars_dir, exist_ok=True)
                name_clean = re.sub(r'[\\/*?:\[\]]', '', str(name_hint or "avatar"))
                h_uid = hashlib.md5(front_card_path.encode("utf-8", errors="ignore")).hexdigest()[:6]
                av_path = os.path.join(avatars_dir, f"avatar_{name_clean}_{h_uid}.jpg")
                av.save(av_path, "JPEG", quality=95, dpi=(300, 300))
                return av_path
    except Exception as e:
        print(f"[Template] 自动切取头像异常: {e}")
    return ""


def _build_docx_context(doc: DocxTemplate, data: dict) -> dict:
    """构建 Word 模板渲染上下文，包括文本字段和图片字段"""
    context = {}
    for placeholder, key in PLACEHOLDER_MAP.items():
        value = data.get(key, "")
        context[placeholder] = str(value) if isinstance(value, int) else value

    # 英文通用键补充
    for k, v in data.items():
        if isinstance(v, (str, int)):
            context[k] = str(v)

    # 核心设计：极速纯 OCR 模式下未生成切片时，图片占位符直接留空白，不强制切图，保证极速流畅
    raw_front = data.get("front_image_path", "")
    raw_back = data.get("back_image_path", "")
    avatar_path = data.get("avatar_path", "")

    # 只有当路径本身就是切好的标准 PNG/JPG 卡片时才嵌入，否则直接留空白
    front_path = raw_front if (raw_front and os.path.basename(raw_front).lower().startswith("front_") and raw_front.lower().endswith(".png") and os.path.exists(raw_front)) else ""
    back_path = raw_back if (raw_back and os.path.basename(raw_back).lower().startswith("back_") and raw_back.lower().endswith(".png") and os.path.exists(raw_back)) else ""
    if avatar_path and not os.path.exists(avatar_path):
        avatar_path = ""



    # 1. 头像图片占位符支持 ({{头像}} / {{照片}} / {{avatar}} / {{photo}})
    img_avatar = _make_safe_inline_image(doc, avatar_path, target_width_mm=28, default_ratio=1.25)
    context["头像"] = img_avatar
    context["照片"] = img_avatar
    context["avatar"] = img_avatar
    context["photo"] = img_avatar

    # 2. 正面卡面占位符支持 ({{正面照片}} / {{正面}} / {{front_img}})
    # 按照中国二代证标准比例 85.6mm x 54.0mm (比例 0.6308) 嵌入带有标准圆角的高清 PNG
    img_front = _make_safe_inline_image(doc, front_path, target_width_mm=85.6, default_ratio=0.6308)
    context["正面照片"] = img_front
    context["正面"] = img_front
    context["front_img"] = img_front

    # 3. 反面卡面占位符支持 ({{反面照片}} / {{反面}} / {{back_img}})
    img_back = _make_safe_inline_image(doc, back_path, target_width_mm=85.6, default_ratio=0.6308)
    context["反面照片"] = img_back
    context["反面"] = img_back
    context["back_img"] = img_back

    return context


def fill_word_template(template_path: str, data: dict, output_path: str):
    """使用 docxtpl 填充 Word 模板"""
    doc = DocxTemplate(template_path)
    context = _build_docx_context(doc, data)
    doc.render(context)
    doc.save(output_path)


def fill_excel_template(template_path: str, data: dict, output_path: str):
    """填充 Excel 模板"""
    wb = load_workbook(template_path)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.value and isinstance(cell.value, str):
                    new_value = cell.value
                    for placeholder, key in PLACEHOLDER_MAP.items():
                        tag = "{{" + placeholder + "}}"
                        if tag in new_value:
                            value = data.get(key, "")
                            replacement = str(value) if isinstance(value, int) else value
                            new_value = new_value.replace(tag, str(replacement))
                    if new_value != cell.value:
                        cell.value = new_value
    wb.save(output_path)


def fill_template(template_path: str, data: dict, output_path: str):
    """根据模板类型分发填充"""
    ext = os.path.splitext(template_path)[1].lower()
    if ext == ".docx":
        fill_word_template(template_path, data, output_path)
    elif ext in (".xlsx", ".xls"):
        fill_excel_template(template_path, data, output_path)
    else:
        raise ValueError(f"不支持的模板格式: {ext}")


def batch_fill_template(template_path: str, data_list: list[dict], output_dir: str) -> list[str]:
    """批量填充模板，每人生成一份独立文件"""
    ext = os.path.splitext(template_path)[1].lower()
    os.makedirs(output_dir, exist_ok=True)

    output_files = []
    for data in data_list:
        name = data.get("name", "未知")
        filename = f"{name}_filled{ext}"
        output_path = os.path.join(output_dir, filename)

        counter = 1
        while os.path.exists(output_path):
            filename = f"{name}_filled_{counter}{ext}"
            output_path = os.path.join(output_dir, filename)
            counter += 1

        fill_template(template_path, data, output_path)
        output_files.append(output_path)

    return output_files


def merge_fill_template(template_path: str, data_list: list[dict], output_path: str) -> str:
    """
    邮件合并模式：将所有人员的数据依次填充模板，并合并到同一个文件中。
    - Word 模板 (.docx)：每人自动分页合并为单个长文档
    - Excel 模板 (.xlsx)：每个人生成一个独立 Sheet 工作表，保存在同一个工作簿中
    """
    ext = os.path.splitext(template_path)[1].lower()
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    if ext == ".docx":
        from docx import Document
        temp_files = []
        try:
            for i, data in enumerate(data_list):
                doc = DocxTemplate(template_path)
                context = _build_docx_context(doc, data)
                doc.render(context)
                tmp = os.path.join(tempfile.gettempdir(), f"id_merge_item_{i}_{os.getpid()}.docx")
                doc.save(tmp)
                temp_files.append(tmp)

            if not temp_files:
                return output_path

            import copy
            from io import BytesIO
            from docx.oxml.ns import qn

            base_doc = Document(temp_files[0])

            for f in temp_files[1:]:
                base_doc.add_page_break()
                sub_doc = Document(f)

                # 1. 将子文档中的独有图片复制注入到 base_doc，并建立 rId 映射
                rid_map = {}
                for rel_id, rel in sub_doc.part.rels.items():
                    if "image" in rel.reltype:
                        try:
                            img_blob = rel.target_part.blob
                            new_rid, _ = base_doc.part.get_or_add_image(BytesIO(img_blob))
                            rid_map[rel_id] = new_rid
                        except Exception as e:
                            print(f"[Template] 迁移图片资源异常: {e}")

                # 2. 追加节点并重写图片嵌入标识 r:embed
                for element in sub_doc.element.body:
                    if element.tag.endswith("sectPr"):
                        continue
                    new_element = copy.deepcopy(element)
                    for blip in new_element.xpath(".//a:blip"):
                        old_rid = blip.get(qn("r:embed"))
                        if old_rid in rid_map:
                            blip.set(qn("r:embed"), rid_map[old_rid])
                    for hlink in new_element.xpath(".//w:hyperlink"):
                        old_hid = hlink.get(qn("r:id"))
                        if old_hid in rid_map:
                            hlink.set(qn("r:id"), rid_map[old_hid])

                    base_doc.element.body.append(new_element)

            base_doc.save(output_path)
            return output_path
        finally:
            for f in temp_files:
                try:
                    if os.path.exists(f):
                        os.remove(f)
                except Exception:
                    pass

    elif ext in (".xlsx", ".xls"):
        wb = load_workbook(template_path)
        base_sheet = wb.active

        sheet_names_seen = set()
        for i, data in enumerate(data_list):
            raw_name = data.get("name") or f"人员_{i+1}"
            safe_name = re.sub(r'[\\/*?:\[\]]', '', str(raw_name))[:25]
            if not safe_name:
                safe_name = f"Sheet_{i+1}"
            
            s_name = safe_name
            c = 1
            while s_name in sheet_names_seen or s_name in wb.sheetnames:
                s_name = f"{safe_name}_{c}"
                c += 1
            sheet_names_seen.add(s_name)

            ws = wb.copy_worksheet(base_sheet)
            ws.title = s_name

            for row in ws.iter_rows():
                for cell in row:
                    if cell.value and isinstance(cell.value, str):
                        new_val = cell.value
                        for placeholder, key in PLACEHOLDER_MAP.items():
                            tag = "{{" + placeholder + "}}"
                            if tag in new_val:
                                val = data.get(key, "")
                                new_val = new_val.replace(tag, str(val))
                        if new_val != cell.value:
                            cell.value = new_val

        # 移除原始空白模板 sheet
        if len(wb.worksheets) > 1 and base_sheet in wb.worksheets:
            wb.remove(base_sheet)

        wb.save(output_path)
        return output_path
    else:
        raise ValueError(f"不支持合并的模板格式: {ext}")
