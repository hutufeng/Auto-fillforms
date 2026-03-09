# -*- coding: utf-8 -*-
"""身份证号码计算模块：提取生日、年龄、性别，校验号码有效性"""

from datetime import datetime, date
import re


def validate_id(id_number: str) -> bool:
    """校验18位身份证号码（含末位 X 的校验码验证）"""
    if not id_number or len(id_number) != 18:
        return False
    if not re.match(r'^\d{17}[\dXx]$', id_number):
        return False

    # 加权因子
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    # 校验码对照表（mod 11 的余数 → 校验码）
    check_codes = ['1', '0', 'X', '9', '8', '7', '6', '5', '4', '3', '2']

    total = sum(int(id_number[i]) * weights[i] for i in range(17))
    expected = check_codes[total % 11]
    return id_number[-1].upper() == expected


def extract_birthday(id_number: str) -> str:
    """从身份证号提取生日 → 'YYYY-MM-DD'"""
    if not id_number or len(id_number) < 14:
        return ""
    year = id_number[6:10]
    month = id_number[10:12]
    day = id_number[12:14]
    try:
        date(int(year), int(month), int(day))
        return f"{year}-{month}-{day}"
    except ValueError:
        return ""


def calc_age(id_number: str) -> int:
    """根据当前日期计算周岁"""
    birthday_str = extract_birthday(id_number)
    if not birthday_str:
        return 0
    birthday = datetime.strptime(birthday_str, "%Y-%m-%d").date()
    today = date.today()
    age = today.year - birthday.year
    if (today.month, today.day) < (birthday.month, birthday.day):
        age -= 1
    return age


def extract_gender(id_number: str) -> str:
    """第17位奇数='男', 偶数='女'"""
    if not id_number or len(id_number) < 17:
        return ""
    try:
        return "男" if int(id_number[16]) % 2 == 1 else "女"
    except ValueError:
        return ""
