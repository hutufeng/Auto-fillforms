# -*- coding: utf-8 -*-
"""商业授权管理器单元测试"""

import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from auth_manager import AuthManager, get_machine_code, _verify_signature, PUBLIC_KEY_PEM


class TestAuthManager(unittest.TestCase):

    def test_machine_code_format(self):
        hwid = get_machine_code()
        self.assertTrue(hwid.startswith("HWID-"))
        parts = hwid.split("-")
        self.assertGreaterEqual(len(parts), 2)

    def test_unactivated_status(self):
        manager = AuthManager()
        status = manager.get_status()
        self.assertEqual(status["product_id"], "APP-20261017-781")
        self.assertIn("machine_code", status)

    def test_verify_signature_invalid(self):
        # 伪造签名测试 (必须拒绝)
        fake_payload = b'{"test":"fake"}'
        fake_sig = "TUlBQ0FRRUNBREFB..."
        self.assertFalse(_verify_signature(PUBLIC_KEY_PEM, fake_payload, fake_sig))


if __name__ == "__main__":
    unittest.main()
