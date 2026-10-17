# -*- coding: utf-8 -*-
"""核心功能与安全性单元测试套件"""

import unittest
import os
import sys

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from id_calculator import validate_id, extract_birthday, calc_age, extract_gender
from id_parser import parse_front, parse_back, is_front_side, is_back_side
from security import safe_filename, is_safe_path
from config import BASE_DIR, USER_TEMPLATES_DIR


class TestIdCalculator(unittest.TestCase):
    """测试身份证号码解析与校验算法"""

    def test_validate_id_valid(self):
        # 校验合法的身份证号码（含校验位为数字和 X 的情况）
        # 11010519491231002X 为标准校验码示例
        self.assertTrue(validate_id("11010519491231002X"))
        self.assertTrue(validate_id("11010519491231002x"))

    def test_validate_id_invalid(self):
        # 错误校验码
        self.assertFalse(validate_id("110105194912310021"))
        # 长度不足或非法字符
        self.assertFalse(validate_id("12345"))
        self.assertFalse(validate_id("11010519491231002A"))
        self.assertFalse(validate_id(""))

    def test_extract_birthday(self):
        self.assertEqual(extract_birthday("110105199003072345"), "1990-03-07")
        self.assertEqual(extract_birthday("invalid_id"), "")

    def test_extract_gender(self):
        # 第17位奇数为男，偶数为女
        self.assertEqual(extract_gender("110105199003072315"), "男")
        self.assertEqual(extract_gender("110105199003072325"), "女")
        self.assertEqual(extract_gender(""), "")


class TestIdParser(unittest.TestCase):
    """测试 OCR 文本解析"""

    def test_is_front_and_back(self):
        front_lines = ["姓名 张三", "性别 男 民族 汉", "公民身份号码 11010519491231002X"]
        back_lines = ["中华人民共和国", "居民身份证", "签发机关 北京市公安局朝阳分局", "有效期限 2020.01.01-2040.01.01"]

        self.assertTrue(is_front_side(front_lines))
        self.assertFalse(is_back_side(front_lines))

        self.assertTrue(is_back_side(back_lines))
        self.assertFalse(is_front_side(back_lines))

    def test_parse_front_with_invalid_checksum(self):
        # 提供一个校验码错误的号码，应正常解析但附带警告信息
        lines = [
            "姓名 张三",
            "性别 男 民族 汉",
            "出生 1990年3月7日",
            "住址 北京市朝阳区某某路1号",
            "公民身份号码 110105199003072310"  # 故意构造错误末位
        ]
        res = parse_front(lines)
        self.assertEqual(res["name"], "张三")
        self.assertEqual(res["gender"], "男")
        self.assertEqual(res["id_number"], "110105199003072310")
        self.assertIn("_warnings", res)
        self.assertTrue(any("校验位不匹配" in w for w in res["_warnings"]))


class TestSecurityHelpers(unittest.TestCase):
    """测试安全与防路径穿越辅助函数"""

    def test_safe_filename(self):
        # 正常中文文件名保留
        self.assertEqual(safe_filename("张三_正面.jpg"), "张三_正面.jpg")
        # 路径穿越攻击清理
        self.assertEqual(safe_filename("../../etc/passwd"), "passwd")
        self.assertEqual(safe_filename("..\\..\\config.py"), "config.py")
        # 空文件名兜底
        self.assertTrue(safe_filename("").startswith("file_"))

    def test_is_safe_path(self):
        # 合法路径
        valid_path = os.path.join(USER_TEMPLATES_DIR, "template.docx")
        self.assertTrue(is_safe_path(USER_TEMPLATES_DIR, valid_path))

        # 恶意跨目录路径
        evil_path = os.path.join(USER_TEMPLATES_DIR, "..", "config.py")
        self.assertFalse(is_safe_path(USER_TEMPLATES_DIR, evil_path))


if __name__ == "__main__":
    unittest.main()
