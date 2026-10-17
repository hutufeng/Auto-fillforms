# -*- coding: utf-8 -*-
"""
商业授权管理模块 (HutuAuthorization SDK Python 适配层)
产品 ID: APP-20261017-781
功能位: standard (基础核心版)
认证服务器: https://lic-api.363723.xyz
"""

from __future__ import annotations
import os
import sys
import json
import base64
import hashlib
import platform
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from functools import wraps

# 密码学验签支持 (双模自适应)
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.serialization import load_pem_public_key

# ====== 商业产品配置 ======
PRODUCT_ID = "APP-20261017-781"
PRODUCT_NAME = "身份证ocr"
REQUIRED_FEATURE = "standard"
SERVER_URL = os.getenv("AUTH_SERVER_URL", "https://lic-api.363723.xyz").rstrip('/')
CLIENT_VERSION = "1.0.0"

PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEwZnhfsDvPiCnHdbs3BOdpsIFPVIY
cyD5ZehtVq+sunQ8Wp+Nzeydu10K7V6k+/lNf+0FQEvG2cYWzkGloKXDrQ==
-----END PUBLIC KEY-----"""

# 本地凭证路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LICENSE_FILE = os.path.join(BASE_DIR, "license.lic")
TOKEN_FILE = os.path.join(BASE_DIR, "license.lic.token")


def get_machine_code() -> str:
    """
    采集标准 3 选 2 硬件指纹生成机器码
    格式: HWID-XXXXXXXX-YYYYYYYY
    """
    sys_name = platform.system().lower()
    raw_ids = []

    if "windows" in sys_name:
        try:
            # 1. 尝试主板/系统 UUID
            cmd_uuid = "wmic csproduct get uuid"
            out_uuid = subprocess.check_output(cmd_uuid, shell=True, text=True, stderr=subprocess.DEVNULL)
            uuid_val = [line.strip() for line in out_uuid.splitlines() if line.strip() and "UUID" not in line.upper()]
            if uuid_val:
                raw_ids.append(uuid_val[0])
        except Exception:
            pass

        try:
            # 2. 尝试硬盘序列号
            cmd_disk = "wmic diskdrive get serialnumber"
            out_disk = subprocess.check_output(cmd_disk, shell=True, text=True, stderr=subprocess.DEVNULL)
            disk_val = [line.strip() for line in out_disk.splitlines() if line.strip() and "SERIALNUMBER" not in line.upper()]
            if disk_val:
                raw_ids.append(disk_val[0])
        except Exception:
            pass

        try:
            # 3. 尝试 CPU ID / 计算机名
            cmd_cpu = "wmic cpu get processorid"
            out_cpu = subprocess.check_output(cmd_cpu, shell=True, text=True, stderr=subprocess.DEVNULL)
            cpu_val = [line.strip() for line in out_cpu.splitlines() if line.strip() and "PROCESSORID" not in line.upper()]
            if cpu_val:
                raw_ids.append(cpu_val[0])
        except Exception:
            pass

    if len(raw_ids) < 2:
        raw_ids.append(platform.node())
        raw_ids.append(platform.processor() or "DEFAULT_CPU")

    part1 = hashlib.sha256(raw_ids[0].encode('utf-8')).hexdigest()[:8].upper()
    part2 = hashlib.sha256(raw_ids[1].encode('utf-8')).hexdigest()[:8].upper()
    return f"HWID-{part1}-{part2}"


def _verify_signature(public_key_pem: str, data_bytes: bytes, sig_base64: str) -> bool:
    """
    ECDSA P-256 双模验签 (标准 DER Sequence / 64字节 IEEE P1363 自适应)
    """
    try:
        pub_key = load_pem_public_key(public_key_pem.encode('utf-8'))
        sig_bytes = base64.b64decode(sig_base64)

        if len(sig_bytes) == 64:
            r = int.from_bytes(sig_bytes[:32], "big")
            s = int.from_bytes(sig_bytes[32:], "big")
            sig_bytes = encode_dss_signature(r, s)

        pub_key.verify(sig_bytes, data_bytes, ec.ECDSA(hashes.SHA256()))
        return True
    except Exception:
        return False


def _extract_signable_payload(data: dict) -> str:
    """严格与 C# 服务端 ExtractSignablePayload 对齐的验签明文构造"""
    sb = []
    def append_val(val):
        if isinstance(val, bool):
            sb.append(("True" if val else "False") + '|')
        else:
            sb.append(str(val) + '|')

    for k in ['license_id', 'product_id', 'customer_name', 'max_version', 'max_build_date', 'allow_vm']:
        if k in data:
            append_val(data[k])

    hw = data.get('hardware_policy', {})
    for k in ['bind_enabled', 'f1', 'f2', 'f3', 'tolerance']:
        if k in hw:
            append_val(hw[k])

    tp = data.get('time_policy', {})
    for k in ['type', 'expire_date', 'duration_days']:
        if k in tp:
            append_val(tp[k])

    ep = data.get('encrypted_payload', '')
    if ep:
        sb.append(str(ep))

    return ''.join(sb)


class AuthManager:
    """单例授权管理器"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_manager()
        return cls._instance

    def _init_manager(self):
        self.machine_code = get_machine_code()
        self.public_key = PUBLIC_KEY_PEM
        self.product_id = PRODUCT_ID
        self.server_url = SERVER_URL
        self.required_feature = REQUIRED_FEATURE

    def get_token(self) -> str:
        if os.path.exists(TOKEN_FILE):
            try:
                with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
                    return f.read().strip()
            except Exception:
                pass
        return ""

    def verify_local_license(self) -> tuple[bool, str, dict]:
        """
        本地严密验签 (离线验证)
        返回: (is_valid, message, info_dict)
        """
        if not os.path.exists(LICENSE_FILE):
            return False, "未激活授权，请在客户端输入卡密激活", {}

        try:
            with open(LICENSE_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                return False, "授权凭证为空", {}

            # 解析 JSON 凭证
            lic_data = json.loads(content)
            sig_b64 = lic_data.get("signature", "")
            if not sig_b64:
                return False, "凭证缺失签名", {}

            # 严格构建验签明文
            payload_str = _extract_signable_payload(lic_data)

            # 1. 签名验证
            if not _verify_signature(self.public_key, payload_str.encode('utf-8'), sig_b64):
                return False, "授权签名校验未通过，凭证非法或已被篡改", {}

            # 2. 产品 ID 比对
            lic_prod = lic_data.get("product_id", "")
            if lic_prod and lic_prod.upper() != self.product_id.upper():
                return False, f"授权与当前产品不匹配 (要求 {self.product_id})", {}

            # 3. 有效期校验
            tp = lic_data.get("time_policy", {})
            tp_type = tp.get("type", "perpetual")
            is_perpetual = tp_type == "perpetual" or lic_data.get("is_perpetual", False)
            if not is_perpetual:
                exp_str = tp.get("expire_date", "")
                if exp_str:
                    try:
                        exp_dt = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                        if datetime.now(timezone.utc) > exp_dt:
                            return False, "授权已到期，请续费激活", lic_data
                    except Exception:
                        pass

            # 4. 功能位校验 (需具备 standard 权限)
            features = lic_data.get("features", [])
            if self.required_feature not in features:
                return False, f"当前授权未包含核心功能 [{self.required_feature}]", lic_data

            return True, "授权有效", lic_data

        except Exception as e:
            return False, f"凭证解析异常: {str(e)}", {}

    def get_status(self) -> dict:
        """获取综合授权状态信息 (供前端展示)"""
        is_valid, msg, lic_data = self.verify_local_license()
        remaining_days = -1
        expire_at_str = "永久有效"

        if is_valid:
            tp = lic_data.get("time_policy", {})
            tp_type = tp.get("type", "perpetual")
            is_perpetual = tp_type == "perpetual" or lic_data.get("is_perpetual", False)
            if not is_perpetual:
                exp_str = tp.get("expire_date", "")
                if exp_str:
                    try:
                        exp_dt = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                        diff_sec = (exp_dt - datetime.now(timezone.utc)).total_seconds()
                        remaining_days = max(0, int(diff_sec // 86400))
                        expire_at_str = exp_dt.strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        expire_at_str = exp_str
            else:
                expire_at_str = "永久有效"

        return {
            "is_valid": is_valid,
            "message": msg,
            "product_id": self.product_id,
            "product_name": PRODUCT_NAME,
            "machine_code": self.machine_code,
            "is_perpetual": (lic_data.get("time_policy", {}).get("type") == "perpetual") if is_valid else False,
            "remaining_days": remaining_days,
            "expire_at": expire_at_str,
            "features": lic_data.get("features", []) if is_valid else [],
            "license_id": lic_data.get("license_id", "") if is_valid else "",
            "allow_unbind": True
        }

    def activate_online(self, auth_code: str) -> tuple[bool, str]:
        """联网提交 16 位卡密激活"""
        code = auth_code.strip()
        if not code:
            return False, "激活码不能为空"

        payload = {
            "product_id": self.product_id,
            "auth_code": code,
            "machine_code": self.machine_code,
            "client_version": CLIENT_VERSION,
            "platform": "Windows"
        }

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "HutuClientPython/1.0"
        }

        try:
            req = urllib.request.Request(
                f"{self.server_url}/api/v1/activate",
                data=json.dumps(payload).encode('utf-8'),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get("code") == 0:
                    lic_content = data["data"]["license_file_content"]
                    # 写入 license.lic
                    with open(LICENSE_FILE, "w", encoding="utf-8") as f:
                        f.write(lic_content)

                    # 写入 token
                    token = data["data"].get("access_token", "")
                    if token:
                        with open(TOKEN_FILE, "w", encoding="utf-8") as tf:
                            tf.write(token)

                    return True, "激活成功，核心功能已解锁！"
                else:
                    return False, data.get("message", "激活失败，卡密错误或已失效")
        except urllib.error.HTTPError as he:
            try:
                raw_body = he.read().decode('utf-8', errors='replace')
                err_data = json.loads(raw_body)
                msg = err_data.get("message") or err_data.get("error") or f"HTTP {he.code}"
                return False, f"{msg}"
            except Exception:
                return False, f"激活请求失败: HTTP {he.code}"
        except Exception as e:
            return False, f"无法连接认证服务器: {str(e)}"

    def unbind_online(self, auth_code: str) -> tuple[bool, str]:
        """换机解绑"""
        code = auth_code.strip()
        if not code:
            return False, "请输入原激活码以进行解绑"

        payload = {
            "auth_code": code,
            "machine_code": self.machine_code
        }
        headers = {"Content-Type": "application/json"}
        token = self.get_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            req = urllib.request.Request(
                f"{self.server_url}/api/v1/unbind",
                data=json.dumps(payload).encode('utf-8'),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get("code") == 0:
                    for p in [LICENSE_FILE, TOKEN_FILE]:
                        if os.path.exists(p):
                            try: os.remove(p)
                            except: pass
                    return True, "解绑成功，已恢复未激活状态"
                return False, data.get("message", "解绑失败")
        except Exception as e:
            return False, f"解绑异常: {str(e)}"


# 单例实例
auth_manager = AuthManager()


def require_auth(func):
    """API 路由守门装饰器"""
    @wraps(func)
    def decorated_view(*args, **kwargs):
        from flask import jsonify
        is_valid, msg, _ = auth_manager.verify_local_license()
        if not is_valid:
            return jsonify({
                "error": "软件未激活或授权已过期",
                "auth_required": True,
                "detail": msg,
                "machine_code": auth_manager.machine_code
            }), 403
        return func(*args, **kwargs)
    return decorated_view
