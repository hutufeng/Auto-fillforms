# -*- coding: utf-8 -*-
"""身份证 OCR 文本解析模块：将 OCR 原始文本行解析为结构化身份证数据"""

import re
from id_calculator import extract_birthday, calc_age, extract_gender, validate_id


def _find_id_number(lines: list[str]) -> str:
    """从文本行中查找18位身份证号码"""
    full_text = "".join(lines)
    # 匹配 17位数字 + 1位数字或X/x
    match = re.search(r'\d{17}[\dXx]', full_text)
    if match:
        id_num = match.group()
        # 末位统一大写
        return id_num[:-1] + id_num[-1].upper()
    return ""


def _extract_field(lines: list[str], keyword: str) -> str:
    """根据关键词提取后续文本"""
    for line in lines:
        if keyword in line:
            # 取关键词后面的文本
            idx = line.index(keyword) + len(keyword)
            value = line[idx:].strip()
            # 去除前面可能的冒号、空格
            value = re.sub(r'^[:\s：]+', '', value)
            return value
    return ""


def is_front_side(lines: list[str]) -> bool:
    """判断是否为身份证正面（人像面）"""
    full_text = " ".join(lines)
    has_id = bool(re.search(r'\d{17}[\dXx]', full_text))
    has_name_kw = any(kw in full_text for kw in ["姓名", "性别", "民族", "住址", "公民身份号码", "公民身份证号码"])
    return has_id or has_name_kw


def is_back_side(lines: list[str]) -> bool:
    """判断是否为身份证反面（国徽面）"""
    full_text = " ".join(lines)
    return "签发机关" in full_text or "有效期" in full_text


def parse_front(lines: list[str]) -> dict:
    """
    解析身份证正面（人像面）OCR 文本。
    
    返回字段：name, gender, ethnicity, birthday, age, id_number, address
    """
    result = {
        "name": "",
        "gender": "",
        "ethnicity": "",
        "birthday": "",
        "age": 0,
        "id_number": "",
        "address": "",
    }

    if not lines:
        return result

    # 1. 提取身份证号码
    id_number = _find_id_number(lines)
    if id_number:
        result["id_number"] = id_number
        result["birthday"] = extract_birthday(id_number)
        result["age"] = calc_age(id_number)
        result["gender"] = extract_gender(id_number)

    # 2. 提取姓名
    name = _extract_field(lines, "姓名")
    if name:
        # 去掉可能混入的 "性别" 关键词
        name = re.split(r'性别|民族', name)[0].strip()
        result["name"] = name

    # 3. 提取民族
    ethnicity = _extract_field(lines, "民族")
    if ethnicity:
        # 民族可能跟着其他内容，只取第一个词
        ethnicity = re.split(r'\s+', ethnicity)[0]
        result["ethnicity"] = ethnicity

    # 4. 提取住址（可能跨多行，OCR 行顺序可能不规则）
    # 策略：先找到"住址"所在行位置，然后向前回溯和向后采集
    address_lines = []
    known_keywords = ["姓名", "性别", "民族", "出生", "公民", "身份证", "号码"]

    # 第一步：找到"住址"关键词所在行索引
    addr_label_idx = -1
    for i, line in enumerate(lines):
        if "住址" in line or "住 址" in line:
            addr_label_idx = i
            break

    if addr_label_idx >= 0:
        # 提取"住址"标签同行的文本
        addr_line = lines[addr_label_idx]
        addr_text = re.sub(r'^.*?住\s*址[:\s：]*', '', addr_line).strip()

        # 如果"住址"后没有文本（是独立标签），向前回溯查找地址起始部分
        if not addr_text:
            for j in range(addr_label_idx - 1, -1, -1):
                prev = lines[j].strip()
                if not prev:
                    continue
                # 如果前面的行包含已知关键词，停止回溯
                if any(kw in prev for kw in known_keywords):
                    # 可能是 "出生1986年3月9日四川省..." 这种混合行
                    # 尝试提取"出生"后面日期之后的地址部分
                    date_addr = re.search(r'(?:出生|出 生)\s*\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日(.+)', prev)
                    if date_addr:
                        tail = date_addr.group(1).strip()
                        if tail:
                            address_lines.insert(0, tail)
                    break
                # 纯数字跳过
                if re.match(r'^\d+$', prev):
                    continue
                # 排除身份证号码行
                if re.search(r'\d{17}[\dXx]', prev):
                    continue
                # 这行很可能是地址的前半部分
                address_lines.insert(0, prev)
                # 只回溯一行（地址前半部分通常紧挨着"住址"标签）
                break
        else:
            address_lines.append(addr_text)

        # 向后采集（"住址"行之后的内容）
        for k in range(addr_label_idx + 1, len(lines)):
            cleaned = lines[k].strip()
            if not cleaned:
                continue
            # 遇到身份证号码则停止
            if re.search(r'\d{17}[\dXx]', cleaned):
                break
            # 遇到截止关键词则停止
            if any(kw in cleaned for kw in known_keywords):
                break
            # 纯数字行跳过
            if re.match(r'^\d+$', cleaned):
                continue
            address_lines.append(cleaned)

    if address_lines:
        result["address"] = "".join(address_lines)

    return result


def parse_back(lines: list[str]) -> dict:
    """
    解析身份证反面（国徽面）OCR 文本。
    
    返回字段：authority, validity
    """
    result = {
        "authority": "",
        "validity": "",
    }

    if not lines:
        return result

    # 1. 签发机关（可能跨行：标签和内容分在两行）
    authority = _extract_field(lines, "签发机关")
    if not authority:
        # "签发机关"作为独立行，内容在下一行
        for i, line in enumerate(lines):
            if "签发机关" in line:
                # 该行只有标签没有内容，取下一个非空行
                text_after = re.sub(r'^.*?签发机关[:\s：]*', '', line).strip()
                if not text_after:
                    for j in range(i + 1, len(lines)):
                        next_line = lines[j].strip()
                        if next_line and "有效期" not in next_line:
                            authority = next_line
                            break
                break
    if authority:
        result["authority"] = authority

    # 2. 有效期限 —— 格式：YYYY.MM.DD-YYYY.MM.DD 或 YYYY.MM.DD-长期
    full_text = " ".join(lines)

    # 尝试匹配完整有效期
    validity_match = re.search(
        r'(\d{4})[.\-年](\d{2})[.\-月](\d{2})[日]?\s*[-—~至]\s*(\d{4}[.\-年]\d{2}[.\-月]\d{2}[日]?|长期)',
        full_text
    )
    if validity_match:
        start = f"{validity_match.group(1)}.{validity_match.group(2)}.{validity_match.group(3)}"
        end_raw = validity_match.group(4)
        if end_raw == "长期":
            end = "长期"
        else:
            end_parts = re.findall(r'\d+', end_raw)
            if len(end_parts) >= 3:
                end = f"{end_parts[0]}.{end_parts[1]}.{end_parts[2]}"
            else:
                end = end_raw
        result["validity"] = f"{start}-{end}"
    else:
        # 备选：直接查找有效期关键词后的文本
        validity = _extract_field(lines, "有效期")
        if validity:
            result["validity"] = validity

    return result


def parse_id_card(front_lines: list[str], back_lines: list[str] = None) -> dict:
    """
    综合解析身份证正反面数据。
    
    Args:
        front_lines: 正面 OCR 文本行
        back_lines: 反面 OCR 文本行（可选）
    
    Returns:
        完整的身份证信息字典
    """
    data = parse_front(front_lines)
    if back_lines:
        back_data = parse_back(back_lines)
        data.update(back_data)
    else:
        data["authority"] = ""
        data["validity"] = ""
    return data


def parse_single_image(lines: list[str]) -> dict:
    """
    解析单张图片的 OCR 结果。
    自动判断是正面、反面还是正反面合图。
    
    Returns:
        (data_dict, side_type) 
        side_type: "front", "back", "both", "unknown"
    """
    front = is_front_side(lines)
    back = is_back_side(lines)

    if front and back:
        # 单图包含正反面：尝试按位置拆分
        front_lines = []
        back_lines = []
        in_back = False
        for line in lines:
            if not in_back and ("签发机关" in line or "有效期" in line):
                in_back = True
            if in_back:
                back_lines.append(line)
            else:
                front_lines.append(line)
        data = parse_id_card(front_lines, back_lines)
        return data, "both"
    elif front:
        data = parse_front(lines)
        data["authority"] = ""
        data["validity"] = ""
        return data, "front"
    elif back:
        data = {"name": "", "gender": "", "ethnicity": "", "birthday": "",
                "age": 0, "id_number": "", "address": ""}
        data.update(parse_back(lines))
        return data, "back"
    else:
        return {}, "unknown"
