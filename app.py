# -*- coding: utf-8 -*-
"""Flask 主应用 — 身份证信息自动提取工具"""

import os
import uuid
import json
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file

from config import UPLOAD_DIR, OUTPUT_DIR, USER_TEMPLATES_DIR, SUPPORTED_IMAGE_EXTS
from ocr_client import check_ocr_service, ocr_image
from id_parser import parse_single_image, parse_id_card, is_front_side, is_back_side
from id_calculator import validate_id
from excel_writer import write_to_excel, write_batch_to_excel
from template_filler import fill_template, batch_fill_template
from batch_processor import group_files, process_single_group, process_batch

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB

# 内存中存储识别历史（生产环境应使用数据库）
recognition_history = []


def _allowed_image(filename):
    ext = os.path.splitext(filename)[1].lower()
    return ext in SUPPORTED_IMAGE_EXTS


def _allowed_template(filename):
    ext = os.path.splitext(filename)[1].lower()
    return ext in {".docx", ".xlsx"}


def _save_upload(file, subdir=""):
    """保存上传文件，返回保存路径"""
    target_dir = os.path.join(UPLOAD_DIR, subdir) if subdir else UPLOAD_DIR
    os.makedirs(target_dir, exist_ok=True)
    # 保留原始文件名
    filename = file.filename
    filepath = os.path.join(target_dir, filename)
    # 避免覆盖
    if os.path.exists(filepath):
        name, ext = os.path.splitext(filename)
        filepath = os.path.join(target_dir, f"{name}_{uuid.uuid4().hex[:6]}{ext}")
    file.save(filepath)
    return filepath


# ====== 页面路由 ======

@app.route("/")
def index():
    return render_template("index.html")


# ====== API 路由 ======

@app.route("/api/ocr/status", methods=["GET"])
def ocr_status():
    """检查 OCR 服务状态"""
    online = check_ocr_service()
    return jsonify({"online": online})


@app.route("/api/ocr/recognize", methods=["POST"])
def recognize():
    """
    识别上传的身份证图片。
    支持上传 front（正面）和 back（反面）两个文件字段。
    """
    front_file = request.files.get("front")
    back_file = request.files.get("back")

    if not front_file and not back_file:
        return jsonify({"error": "请上传至少一张身份证图片"}), 400

    front_lines = None
    back_lines = None
    warnings = []

    # 识别正面
    if front_file and _allowed_image(front_file.filename):
        front_path = _save_upload(front_file)
        lines = ocr_image(front_path)
        if lines:
            # 自动判断正反面
            data, side = parse_single_image(lines)
            if side == "both":
                # 单图包含正反面
                data["_warnings"] = ["单图包含正反面，已自动拆分"]
                _add_to_history(data)
                return jsonify({"success": True, "data": _clean_data(data)})
            elif side == "front":
                front_lines = lines
            elif side == "back":
                back_lines = lines
                warnings.append("上传为正面的图片被识别为反面")
        else:
            warnings.append("正面图片 OCR 识别失败")

    # 识别反面
    if back_file and _allowed_image(back_file.filename):
        back_path = _save_upload(back_file)
        lines = ocr_image(back_path)
        if lines:
            data_b, side_b = parse_single_image(lines)
            if side_b == "back":
                back_lines = lines
            elif side_b == "front" and front_lines is None:
                front_lines = lines
                warnings.append("上传为反面的图片被识别为正面")
            elif side_b == "both":
                data_b["_warnings"] = ["单图包含正反面，已自动拆分"]
                _add_to_history(data_b)
                return jsonify({"success": True, "data": _clean_data(data_b)})
            else:
                back_lines = lines
        else:
            warnings.append("反面图片 OCR 识别失败")

    if front_lines is None and back_lines is None:
        return jsonify({"error": "无法识别身份证信息", "warnings": warnings}), 400

    data = parse_id_card(front_lines or [], back_lines)
    data["_warnings"] = warnings
    _add_to_history(data)
    return jsonify({"success": True, "data": _clean_data(data)})


@app.route("/api/batch/upload", methods=["POST"])
def batch_upload():
    """批量上传图片并返回分组预览"""
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "未上传文件"}), 400

    # 创建批次目录
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_dir = os.path.join(UPLOAD_DIR, f"batch_{batch_id}")
    os.makedirs(batch_dir, exist_ok=True)

    saved = 0
    for f in files:
        if f.filename and _allowed_image(f.filename):
            f.save(os.path.join(batch_dir, f.filename))
            saved += 1

    if saved == 0:
        return jsonify({"error": "没有有效的图片文件"}), 400

    # 分组
    groups = group_files(batch_dir)
    group_preview = []
    for name, paths in groups.items():
        group_preview.append({
            "name": name,
            "files": [os.path.basename(p) for p in paths],
            "count": len(paths)
        })

    return jsonify({
        "success": True,
        "batch_id": batch_id,
        "batch_dir": batch_dir,
        "total_files": saved,
        "groups": group_preview
    })


@app.route("/api/batch/recognize", methods=["POST"])
def batch_recognize():
    """批量识别已上传的图片"""
    data = request.get_json()
    batch_dir = data.get("batch_dir")

    if not batch_dir or not os.path.isdir(batch_dir):
        return jsonify({"error": "批次目录不存在"}), 400

    results = process_batch(batch_dir)

    # 添加到历史
    for r in results:
        _add_to_history(r)

    # 清理内部字段
    clean_results = [_clean_data(r) for r in results]
    return jsonify({"success": True, "results": clean_results, "count": len(clean_results)})


@app.route("/api/export/excel", methods=["POST"])
def export_excel():
    """导出数据到 Excel"""
    data = request.get_json()
    records = data.get("records", [])

    if not records:
        return jsonify({"error": "没有数据可导出"}), 400

    filename = f"身份证信息_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    output_path = os.path.join(OUTPUT_DIR, filename)

    write_batch_to_excel(records, output_path)
    return jsonify({"success": True, "filename": filename, "path": f"/api/download/{filename}"})


@app.route("/api/download/<filename>")
def download_file(filename):
    """下载输出文件"""
    filepath = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    return jsonify({"error": "文件不存在"}), 404


@app.route("/api/template/upload", methods=["POST"])
def upload_template():
    """上传模板文件"""
    file = request.files.get("template")
    if not file or not _allowed_template(file.filename):
        return jsonify({"error": "请上传 .docx 或 .xlsx 模板文件"}), 400

    filepath = os.path.join(USER_TEMPLATES_DIR, file.filename)
    file.save(filepath)
    return jsonify({"success": True, "filename": file.filename})


@app.route("/api/template/list", methods=["GET"])
def list_templates():
    """获取模板列表"""
    templates = []
    if os.path.isdir(USER_TEMPLATES_DIR):
        for f in os.listdir(USER_TEMPLATES_DIR):
            ext = os.path.splitext(f)[1].lower()
            if ext in {".docx", ".xlsx"}:
                templates.append({
                    "filename": f,
                    "type": "Word" if ext == ".docx" else "Excel",
                    "size": os.path.getsize(os.path.join(USER_TEMPLATES_DIR, f))
                })
    return jsonify({"templates": templates})


@app.route("/api/template/delete", methods=["POST"])
def delete_template():
    """删除模板"""
    data = request.get_json()
    filename = data.get("filename")
    if not filename:
        return jsonify({"error": "未指定文件名"}), 400
    filepath = os.path.join(USER_TEMPLATES_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        return jsonify({"success": True})
    return jsonify({"error": "文件不存在"}), 404


@app.route("/api/template/fill", methods=["POST"])
def fill_template_api():
    """填充模板"""
    data = request.get_json()
    template_name = data.get("template")
    records = data.get("records", [])

    if not template_name or not records:
        return jsonify({"error": "请指定模板和数据"}), 400

    template_path = os.path.join(USER_TEMPLATES_DIR, template_name)
    if not os.path.exists(template_path):
        return jsonify({"error": f"模板 {template_name} 不存在"}), 404

    ext = os.path.splitext(template_name)[1].lower()

    if len(records) == 1:
        name = records[0].get("name", "output")
        filename = f"{name}_filled{ext}"
        output_path = os.path.join(OUTPUT_DIR, filename)
        # 避免覆盖同名文件
        counter = 1
        while os.path.exists(output_path):
            filename = f"{name}_filled_{counter}{ext}"
            output_path = os.path.join(OUTPUT_DIR, filename)
            counter += 1
        try:
            fill_template(template_path, records[0], output_path)
            return jsonify({"success": True, "files": [{"filename": filename, "path": f"/api/download/{filename}"}]})
        except Exception as e:
            return jsonify({"error": f"模板填充失败: {str(e)}"}), 500
    else:
        try:
            output_files = batch_fill_template(template_path, records, OUTPUT_DIR)
            files = []
            for fp in output_files:
                fn = os.path.basename(fp)
                files.append({"filename": fn, "path": f"/api/download/{fn}"})
            return jsonify({"success": True, "files": files})
        except Exception as e:
            return jsonify({"error": f"批量填充失败: {str(e)}"}), 500


@app.route("/api/history", methods=["GET"])
def get_history():
    """获取识别历史"""
    return jsonify({"records": recognition_history})


@app.route("/api/history/clear", methods=["POST"])
def clear_history():
    """清空识别历史"""
    recognition_history.clear()
    return jsonify({"success": True})


# ====== 辅助函数 ======

def _clean_data(data: dict) -> dict:
    """清理内部字段，返回前端可用数据"""
    clean = {}
    for key in ["name", "gender", "ethnicity", "birthday", "age", "id_number",
                 "address", "authority", "validity"]:
        clean[key] = data.get(key, "")
    # 保留警告信息
    if "_warnings" in data:
        clean["warnings"] = data["_warnings"]
    if "_error" in data:
        clean["error"] = data["_error"]
    if "_group_name" in data:
        clean["group_name"] = data["_group_name"]
    if "_files" in data:
        clean["files"] = data["_files"]
    return clean


def _add_to_history(data: dict):
    """添加到识别历史"""
    clean = _clean_data(data)
    clean["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    recognition_history.append(clean)


if __name__ == "__main__":
    print("=" * 50)
    print("  身份证信息自动提取工具")
    print("  访问: http://127.0.0.1:5000")
    print("=" * 50)
    app.run(debug=True, host="127.0.0.1", port=5000)
