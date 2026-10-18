# -*- coding: utf-8 -*-
"""
身份证OCR · 商业标准版 (纯原生轻量 GUI 客户端)
核心功能：
1. 本地离线高精度 OCR 识别与正反面/合图自动拆分
2. 身份证智能倾斜矫正、标准二代证圆角处理与像素级头像切片
3. 批量图片文件增减管理与双栏识别结果就地核对修改
4. 商业级 A4 身份证彩色/黑白扫描件生成与单人/多页 PDF 导出
5. 邮件合并单文件汇总套打 与 一人一份独立文件套打
6. 极简授权状态栏与一键激活/解绑弹窗
"""

import os
import sys
import re
import json
import shutil
import hashlib
import threading
from datetime import datetime
from PIL import Image, ImageTk

# 保证根目录在 sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# 导入业务核心模块
from auth_manager import auth_manager
from local_ocr import ocr_image, check_ocr_service, get_ocr_engine_name
from id_parser import parse_single_image, parse_id_card, is_front_side, is_back_side
from id_calculator import validate_id
from excel_writer import write_to_excel, write_batch_to_excel
from template_filler import fill_template, batch_fill_template, merge_fill_template
from batch_processor import _extract_base_name, process_single_group, render_pdf_to_images, auto_group_items
from id_scanner import (
    correct_and_crop_card,
    crop_avatar_from_standard_card,
    crop_both_sides_from_single_image,
    generate_a4_scanned_page,
    export_a4_sheets_to_pdf,
    convert_card_to_photocopy
)
from id_cropper import copy_image_to_clipboard
from config import UPLOAD_DIR, OUTPUT_DIR, USER_TEMPLATES_DIR, SUPPORTED_IMAGE_EXTS

# 核心身份证表单字段规范
FORM_FIELDS = [
    ("name", "姓名"),
    ("gender", "性别"),
    ("ethnicity", "民族"),
    ("birthday", "出生日期"),
    ("age", "计算周岁"),
    ("id_number", "身份证号码"),
    ("address", "住址"),
    ("authority", "签发机关"),
    ("validity", "有效期限")
]

# 界面库优先使用 CustomTkinter，无缝回退至标准 Tkinter
USE_CTK = False
try:
    import customtkinter as ctk
    USE_CTK = True
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
except ImportError:
    import tkinter as ctk

import tkinter as tk
from tkinter import ttk, messagebox, filedialog


class AppGUI(ctk.CTk if USE_CTK else tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("身份证信息提取与卡面扫描系统")
        self._init_window_geometry()
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)

        if USE_CTK:
            self.configure(fg_color="#0b0f19")

        # 设置应用图标
        self._set_app_icon()

        # 状态变量 - 单图
        self.front_path = ""
        self.back_path = ""
        self.avatar_path = ""
        self.avatar_photo_image = None
        self.current_data = {}

        # 状态变量 - 批量
        self.batch_files_map = {}  # filepath -> dict(name, size, status, base_name)
        self.batch_groups = {}     # base_name -> [filepaths]
        self.batch_results = []    # [dict]
        self.current_selected_group = None

        self._build_header()
        self._build_tabs()
        self._update_auth_ui()

    def _init_window_geometry(self):
        """自适应屏幕可用工作区并记忆恢复上次窗口大小与位置布局"""
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()

        # 屏幕可用高度预估（扣除 Windows 底部任务栏 60px 与顶部余量）
        avail_h = max(560, screen_h - 70)
        # 默认最佳比例：宽度 82% 且不超过 1160，高度 86% 且不超过 720
        default_w = min(1160, max(940, int(screen_w * 0.82)))
        default_h = min(720, max(560, int(avail_h * 0.86)))
        default_x = max(0, (screen_w - default_w) // 2)
        default_y = max(0, (avail_h - default_h) // 2)

        cfg_file = os.path.join(BASE_DIR, "window_config.json")
        loaded = False
        if os.path.exists(cfg_file):
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if cfg.get("maximized"):
                    self.geometry(f"{default_w}x{default_h}+{default_x}+{default_y}")
                    self.after(60, lambda: self.state("zoomed"))
                    loaded = True
                else:
                    gw = int(cfg.get("width", default_w))
                    gh = int(cfg.get("height", default_h))
                    gx = int(cfg.get("x", default_x))
                    gy = int(cfg.get("y", default_y))
                    # 严格校验坐标边界，防止拔掉外接屏幕后窗口悬空在屏幕外
                    if 0 <= gx < screen_w - 150 and 0 <= gy < screen_h - 100 and gw >= 800 and gh >= 500:
                        # 确保窗口下沿绝不超出当前桌面可见区域
                        if gy + gh > screen_h - 40:
                            gh = max(560, screen_h - 40 - gy)
                        self.geometry(f"{gw}x{gh}+{gx}+{gy}")
                        loaded = True
            except Exception:
                pass

        if not loaded:
            self.geometry(f"{default_w}x{default_h}+{default_x}+{default_y}")

        # 设置友好弹性最小规格，绝不超出任何小屏幕桌面
        self.minsize(920, 550)

    def _save_window_config(self):
        """退出前持久化记录当前窗口尺寸与屏幕位置布局"""
        try:
            cfg_file = os.path.join(BASE_DIR, "window_config.json")
            is_max = False
            try:
                if self.state() == "zoomed":
                    is_max = True
            except Exception:
                pass

            if is_max:
                cfg = {"maximized": True}
            else:
                geom = self.geometry()
                m = re.match(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$", geom)
                if m:
                    w, h, x, y = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                    if w >= 800 and h >= 500:
                        cfg = {"maximized": False, "width": w, "height": h, "x": max(0, x), "y": max(0, y)}
                    else:
                        return
                else:
                    return

            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    def _on_window_close(self):
        """窗口关闭前自动保存布局，再安全退出"""
        self._save_window_config()
        self.destroy()

    def _set_app_icon(self):
        """设置窗口图标"""
        icon_ico = os.path.join(BASE_DIR, "assets", "icon.ico")
        icon_png = os.path.join(BASE_DIR, "assets", "icon.png")
        try:
            if os.path.exists(icon_ico):
                self.iconbitmap(icon_ico)
            elif os.path.exists(icon_png):
                img = Image.open(icon_png)
                photo = ImageTk.PhotoImage(img)
                self.iconphoto(True, photo)
        except Exception:
            pass

    def _build_header(self):
        """顶部一体化导航与轻量状态栏 (无缝贯穿，左对齐流式整合)"""
        if USE_CTK:
            header = ctk.CTkFrame(self, height=50, corner_radius=0, fg_color="#0f172a")
            header.pack(fill="x", side="top")

            # 1. 左侧品牌 Logo 与标题
            left_box = ctk.CTkFrame(header, fg_color="transparent")
            left_box.pack(side="left", padx=(18, 10), pady=8)

            icon_png = os.path.join(BASE_DIR, "assets", "icon.png")
            if os.path.exists(icon_png):
                try:
                    pil_img = Image.open(icon_png).resize((24, 24), Image.Resampling.LANCZOS)
                    self.header_logo_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(24, 24))
                    logo_lbl = ctk.CTkLabel(left_box, image=self.header_logo_img, text="")
                    logo_lbl.pack(side="left", padx=(0, 8))
                except Exception:
                    pass

            title_lbl = ctk.CTkLabel(
                left_box, 
                text="身份证信息提取与扫描", 
                font=ctk.CTkFont(size=15, weight="bold"),
                text_color="#f8fafc"
            )
            title_lbl.pack(side="left")

            # 2. 紧随品牌的主工作台导航栏 (完全左对齐流式排布)
            nav_frame = ctk.CTkFrame(header, fg_color="#020617", corner_radius=8)
            nav_frame.pack(side="left", padx=(12, 0), pady=8)

            self.nav_tabs = [
                ("📷 单图高精度识别", "single"),
                ("📁 批量分组套打与扫描件", "batch"),
                ("📄 模板智能管理", "template"),
            ]
            self.nav_btns = {}

            for title, key in self.nav_tabs:
                btn = ctk.CTkButton(
                    nav_frame,
                    text=title,
                    height=28,
                    corner_radius=6,
                    fg_color="#2563eb" if key == "single" else "transparent",
                    hover_color="#1e293b",
                    text_color="#ffffff" if key == "single" else "#94a3b8",
                    font=ctk.CTkFont(size=12, weight="bold" if key == "single" else "normal"),
                    command=lambda k=key: self._switch_nav_tab(k)
                )
                btn.pack(side="left", padx=3, pady=3)
                self.nav_btns[key] = btn

            # 3. 右侧：轻量状态徽章 (客观展示 SDK 状态)
            right_box = ctk.CTkFrame(header, fg_color="transparent")
            right_box.pack(side="right", padx=18, pady=10)

            self.auth_badge_btn = ctk.CTkButton(
                right_box,
                text="● 状态获取中",
                font=ctk.CTkFont(size=11),
                fg_color="#1e293b",
                hover_color="#334155",
                text_color="#34d399",
                border_width=1,
                border_color="#334155",
                height=26,
                corner_radius=13,
                command=self.open_auth_dialog
            )
            self.auth_badge_btn.pack(side="right")

            # 顶栏底部 1px 无缝微分割线 (现代 Web / 桌面一体化标配)
            ctk.CTkFrame(self, height=1, corner_radius=0, fg_color="#1e293b").pack(fill="x", side="top")
        else:
            header = tk.Frame(self, bg="#0f172a", height=45)
            header.pack(fill="x", side="top")
            tk.Label(header, text="身份证信息提取与扫描", font=("微软雅黑", 13, "bold"), fg="#ffffff", bg="#0f172a").pack(side="left", padx=15, pady=8)
            self.auth_badge_btn = tk.Button(header, text="● 授权状态", bg="#1e293b", fg="#34d399", relief="flat", command=self.open_auth_dialog)
            self.auth_badge_btn.pack(side="right", padx=15, pady=8)

    def _switch_nav_tab(self, tab_key: str):
        """顶栏导航联动切换选项卡 (零外层嵌套边框，零隔离圈)"""
        if hasattr(self, "nav_btns"):
            for k, btn in self.nav_btns.items():
                if k == tab_key:
                    btn.configure(fg_color="#2563eb", text_color="#ffffff", font=ctk.CTkFont(size=12, weight="bold"))
                else:
                    btn.configure(fg_color="transparent", text_color="#94a3b8", font=ctk.CTkFont(size=12, weight="normal"))

        if hasattr(self, "pages"):
            for k, page in self.pages.items():
                if k == tab_key:
                    page.pack(fill="both", expand=True)
                else:
                    page.pack_forget()

    def _build_tabs(self):
        """一体化内容工作区 (完全去除 CTkTabview 外层硬边框与隔离层)"""
        if USE_CTK:
            self.content_container = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
            self.content_container.pack(fill="both", expand=True, padx=16, pady=12)

            self.pages = {}
            self.tab_single = ctk.CTkFrame(self.content_container, fg_color="transparent")
            self.tab_batch = ctk.CTkFrame(self.content_container, fg_color="transparent")
            self.tab_template = ctk.CTkFrame(self.content_container, fg_color="transparent")

            self.pages["single"] = self.tab_single
            self.pages["batch"] = self.tab_batch
            self.pages["template"] = self.tab_template

            self._build_single_tab(self.tab_single)
            self._build_batch_tab(self.tab_batch)
            self._build_template_tab(self.tab_template)

            # 默认呈现单图工作台
            self.tab_single.pack(fill="both", expand=True)
        else:
            self.tabview = ttk.Notebook(self)
            self.tabview.pack(fill="both", expand=True, padx=10, pady=10)
            self.tab_single = tk.Frame(self.tabview)
            self.tab_batch = tk.Frame(self.tabview)
            self.tab_template = tk.Frame(self.tabview)
            self.tabview.add(self.tab_single, text="单图识别")
            self.tabview.add(self.tab_batch, text="批量处理")
            self.tabview.add(self.tab_template, text="模板管理")
            self._build_single_tab(self.tab_single)
            self._build_batch_tab(self.tab_batch)
            self._build_template_tab(self.tab_template)

    # ====== 1. 单图高精度识别工作台 (弹性自适应网格) ======

    def _build_single_tab(self, parent):
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=4, minsize=340)
        parent.grid_columnconfigure(1, weight=6, minsize=460)

        # 1.1 左栏：上传与切片卡片
        left_frame = ctk.CTkFrame(parent, fg_color="#131d2e", corner_radius=10, border_width=1, border_color="#1e293b")
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=0)

        ctk.CTkLabel(left_frame, text="📤 上传身份证原件", font=ctk.CTkFont(size=14, weight="bold"), text_color="#f8fafc").pack(anchor="w", padx=16, pady=(14, 8))

        # 正面插槽
        self.front_btn = ctk.CTkButton(
            left_frame,
            text="🖼️ 点击选择【正面 (人像面)】图片/PDF\n(支持单图正反合照自动拆分)",
            font=ctk.CTkFont(size=12),
            height=58,
            fg_color="#0f172a",
            hover_color="#1e293b",
            border_width=1,
            border_color="#334155",
            command=self.select_front_image
        )
        self.front_btn.pack(fill="x", padx=16, pady=4)

        # 反面插槽
        self.back_btn = ctk.CTkButton(
            left_frame,
            text="🖼️ 点击选择【反面 (国徽面)】图片/PDF (可选)",
            font=ctk.CTkFont(size=12),
            height=50,
            fg_color="#0f172a",
            hover_color="#1e293b",
            border_width=1,
            border_color="#334155",
            command=self.select_back_image
        )
        self.back_btn.pack(fill="x", padx=16, pady=4)

        clear_btn = ctk.CTkButton(left_frame, text="重选图片", fg_color="#334155", hover_color="#475569", height=24, width=70, command=self.clear_images)
        clear_btn.pack(anchor="e", padx=16, pady=2)

        # 双模式识别按钮：快速提取 vs 完整识别
        btn_action_box = ctk.CTkFrame(left_frame, fg_color="transparent")
        btn_action_box.pack(fill="x", padx=16, pady=(6, 8))

        self.btn_run_fast_ocr = ctk.CTkButton(
            btn_action_box,
            text="⚡ 快速提取 (纯 OCR)",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            height=36,
            command=lambda: self.run_single_ocr(with_crop=False)
        )
        self.btn_run_fast_ocr.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.btn_run_full_ocr = ctk.CTkButton(
            btn_action_box,
            text="📸 完整识别 (含切片)",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            height=36,
            command=lambda: self.run_single_ocr(with_crop=True)
        )
        self.btn_run_full_ocr.pack(side="right", fill="x", expand=True, padx=(4, 0))

        # 精准头像切片卡片
        avatar_card = ctk.CTkFrame(left_frame, fg_color="#0f172a", corner_radius=8, border_width=1, border_color="#334155")
        avatar_card.pack(fill="both", expand=True, padx=16, pady=(2, 10))

        ctk.CTkLabel(avatar_card, text="📸 自动矫正与精准头像切片", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8").pack(anchor="w", padx=12, pady=(8, 2))

        self.avatar_display = ctk.CTkLabel(avatar_card, text="识别正面后\n自动切取免冠头像", font=ctk.CTkFont(size=11), text_color="#64748b", width=100, height=125, fg_color="#1e293b", corner_radius=6)
        self.avatar_display.pack(pady=6)

        av_btns = ctk.CTkFrame(avatar_card, fg_color="transparent")
        av_btns.pack(fill="x", padx=8, pady=(2, 6))

        btn_copy_avatar = ctk.CTkButton(av_btns, text="📋 复制头像", font=ctk.CTkFont(size=11), fg_color="#0284c7", hover_color="#0369a1", height=28, width=100, command=self.copy_avatar_image)
        btn_copy_avatar.pack(side="left", expand=True, padx=2)

        btn_save_avatar = ctk.CTkButton(av_btns, text="💾 另存头像", font=ctk.CTkFont(size=11), fg_color="#334155", hover_color="#475569", height=28, width=100, command=self.save_avatar_image)
        btn_save_avatar.pack(side="right", expand=True, padx=2)

        # 单人直接导出 A4 扫描件按钮
        btn_single_a4 = ctk.CTkButton(avatar_card, text="🖨️ 导出此人 A4 扫描件 (PDF/JPG)", font=ctk.CTkFont(size=12, weight="bold"), fg_color="#8b5cf6", hover_color="#7c3aed", height=32, command=self.export_single_a4_scan)
        btn_single_a4.pack(fill="x", padx=10, pady=(2, 8))

        # 1.2 右侧结果表单卡片 (自适应拉伸)
        right_frame = ctk.CTkFrame(parent, fg_color="#131d2e", corner_radius=10, border_width=1, border_color="#1e293b")
        right_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=0)

        ctk.CTkLabel(right_frame, text="📋 提取结果 (支持就地核对修改)", font=ctk.CTkFont(size=14, weight="bold"), text_color="#f8fafc").pack(anchor="w", padx=20, pady=(14, 8))

        form_frame = ctk.CTkScrollableFrame(right_frame, fg_color="transparent")
        form_frame.pack(fill="both", expand=True, padx=16, pady=0)

        self.form_entries = {}
        for key, label in FORM_FIELDS:
            row = ctk.CTkFrame(form_frame, fg_color="transparent")
            row.pack(fill="x", pady=3)
            lbl = ctk.CTkLabel(row, text=label + ":", width=85, anchor="e", font=ctk.CTkFont(size=13), text_color="#94a3b8")
            lbl.pack(side="left", padx=(0, 10))
            entry = ctk.CTkEntry(row, height=32, font=ctk.CTkFont(size=13), fg_color="#0f172a", border_color="#334155")
            entry.pack(side="left", fill="x", expand=True)
            self.form_entries[key] = entry

        self.warn_lbl = ctk.CTkLabel(right_frame, text="", font=ctk.CTkFont(size=12), text_color="#f59e0b")
        self.warn_lbl.pack(anchor="w", padx=20, pady=2)

        action_bar = ctk.CTkFrame(right_frame, fg_color="transparent")
        action_bar.pack(fill="x", padx=16, pady=12)

        btn_export = ctk.CTkButton(action_bar, text="📊 导出/追加到 Excel", fg_color="#f59e0b", hover_color="#d97706", height=36, command=self.export_single_excel)
        btn_export.pack(side="left", padx=(0, 10))

        btn_fill = ctk.CTkButton(action_bar, text="📝 套打到 Word/Excel 模板 (含照片)", fg_color="#10b981", hover_color="#059669", height=36, command=self.fill_single_template)
        btn_fill.pack(side="left", padx=10)

    # ====== 2. 批量处理、核对修改与扫描件工作台 (弹性自适应网格) ======

    def _build_batch_tab(self, parent):
        """一体化自适应双栏设计：随窗口拖拉自适应放大缩小，完全消灭外层套娃边框"""
        # 2.1 顶部控制栏
        top_bar = ctk.CTkFrame(parent, fg_color="#131d2e", corner_radius=10, border_width=1, border_color="#1e293b")
        top_bar.pack(fill="x", padx=0, pady=(0, 8))

        btn_add_dir = ctk.CTkButton(top_bar, text="📂 导入文件夹", fg_color="#2563eb", hover_color="#1d4ed8", height=32, width=105, command=self.batch_add_directory)
        btn_add_dir.pack(side="left", padx=(12, 4), pady=8)

        btn_add_files = ctk.CTkButton(top_bar, text="🖼️ 追加文件/PDF", fg_color="#334155", hover_color="#475569", height=32, width=110, command=self.batch_add_files)
        btn_add_files.pack(side="left", padx=4, pady=8)

        btn_del_sel = ctk.CTkButton(top_bar, text="🗑️ 移除所选", fg_color="#dc2626", hover_color="#b91c1c", height=32, width=88, command=self.batch_remove_selected)
        btn_del_sel.pack(side="left", padx=4, pady=8)

        btn_clear = ctk.CTkButton(top_bar, text="🧹 清空", fg_color="#475569", hover_color="#334155", height=32, width=70, command=self.batch_clear_all)
        btn_clear.pack(side="left", padx=4, pady=8)

        self.batch_stats_lbl = ctk.CTkLabel(top_bar, text="共 0 份素材 · 归属 0 位人员", font=ctk.CTkFont(size=12), text_color="#94a3b8")
        self.batch_stats_lbl.pack(side="left", padx=12, pady=8)

        self.btn_run_full_batch = ctk.CTkButton(
            top_bar,
            text="🚀 完整批量处理 (含卡面切片)",
            fg_color="#10b981",
            hover_color="#059669",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=32,
            command=lambda: self.run_batch_ocr(with_crop=True)
        )
        self.btn_run_full_batch.pack(side="right", padx=(4, 12), pady=8)

        self.btn_run_fast_batch = ctk.CTkButton(
            top_bar,
            text="⚡ 极速批量识别 (纯文字)",
            fg_color="#0284c7",
            hover_color="#0369a1",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=32,
            command=lambda: self.run_batch_ocr(with_crop=False)
        )
        self.btn_run_fast_batch.pack(side="right", padx=4, pady=8)

        # 2.2 中间双栏自适应网格容器
        main_panes = ctk.CTkFrame(parent, fg_color="transparent")
        main_panes.pack(fill="both", expand=True, padx=0, pady=0)
        main_panes.grid_rowconfigure(0, weight=1)
        main_panes.grid_columnconfigure(0, weight=4, minsize=380)
        main_panes.grid_columnconfigure(1, weight=6, minsize=480)

        # 左栏：人员批次列表 (弹性缩放)
        left_pane = ctk.CTkFrame(main_panes, fg_color="#131d2e", corner_radius=10, border_width=1, border_color="#1e293b")
        left_pane.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=0)

        ctk.CTkLabel(left_pane, text="📑 人员与素材分组列表 (支持按住 Ctrl/Shift 多选)", font=ctk.CTkFont(size=13, weight="bold"), text_color="#f8fafc").pack(anchor="w", padx=12, pady=(10, 2))

        # 批量识别进度条
        prog_frame = ctk.CTkFrame(left_pane, fg_color="transparent")
        prog_frame.pack(fill="x", padx=10, pady=(2, 4))
        self.batch_progress_bar = ctk.CTkProgressBar(prog_frame, height=8, corner_radius=4, fg_color="#0f172a", progress_color="#38bdf8")
        self.batch_progress_bar.set(0)
        self.batch_progress_bar.pack(fill="x")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Batch.Treeview", background="#0f172a", foreground="#f8fafc", fieldbackground="#0f172a", rowheight=28, borderwidth=0, font=("微软雅黑", 10))
        style.configure("Batch.Treeview.Heading", background="#1e293b", foreground="#94a3b8", font=("微软雅黑", 10, "bold"), borderwidth=0)
        style.map("Batch.Treeview", background=[('selected', '#2563eb')])

        columns = ("idx", "group", "count", "status")
        # 启用 extended 多选模式 (支持 Shift/Ctrl 多选)
        self.batch_tree = ttk.Treeview(left_pane, columns=columns, show="headings", style="Batch.Treeview", selectmode="extended")
        self.batch_tree.heading("idx", text="#")
        self.batch_tree.heading("group", text="人员/分组")
        self.batch_tree.heading("count", text="页/张")
        self.batch_tree.heading("status", text="处理状态")

        self.batch_tree.column("idx", width=36, anchor="center")
        self.batch_tree.column("group", width=140, anchor="w")
        self.batch_tree.column("count", width=55, anchor="center")
        self.batch_tree.column("status", width=175, anchor="center")

        tree_scroll = ttk.Scrollbar(left_pane, orient="vertical", command=self.batch_tree.yview)
        self.batch_tree.configure(yscrollcommand=tree_scroll.set)

        self.batch_tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=6)
        tree_scroll.pack(side="right", fill="y", padx=(0, 6), pady=6)
        self.batch_tree.bind("<<TreeviewSelect>>", self._on_batch_tree_selected)
        # 绑定 Delete 快捷键快速移除，绑定 Ctrl+A 全选
        self.batch_tree.bind("<Delete>", lambda e: self.batch_remove_selected())
        self.batch_tree.bind("<Control-a>", self._select_all_batch_tree)
        self.batch_tree.bind("<Control-A>", self._select_all_batch_tree)

        # 右栏：人员档案就地核对修改面板 (弹性缩放)
        right_pane = ctk.CTkFrame(main_panes, fg_color="#131d2e", corner_radius=10, border_width=1, border_color="#1e293b")
        right_pane.grid(row=0, column=1, sticky="nsew", padx=(4, 0), pady=0)

        r_top = ctk.CTkFrame(right_pane, fg_color="transparent")
        r_top.pack(fill="x", padx=14, pady=(8, 4))

        self.r_person_title = ctk.CTkLabel(r_top, text="👤 当前选中人员档案 (选择左侧条目核对修改)", font=ctk.CTkFont(size=13, weight="bold"), text_color="#38bdf8")
        self.r_person_title.pack(side="left")

        btn_save_item = ctk.CTkButton(r_top, text="💾 保存此人修改", fg_color="#10b981", hover_color="#059669", height=28, width=110, command=self.save_current_batch_item_edit)
        btn_save_item.pack(side="right")

        # 图像预览区
        thumb_bar = ctk.CTkFrame(right_pane, fg_color="#0f172a", corner_radius=8, height=136)
        thumb_bar.pack(fill="x", padx=12, pady=(4, 6))
        thumb_bar.pack_propagate(False)

        # 正面预览
        f_box = ctk.CTkFrame(thumb_bar, fg_color="transparent")
        f_box.pack(side="left", padx=(10, 6), pady=6)
        self.lbl_thumb_front = tk.Label(f_box, text="未选正面", width=16, height=5, bg="#1e293b", fg="#94a3b8", cursor="hand2", relief="flat")
        self.lbl_thumb_front.pack(pady=(0, 2))
        self.lbl_thumb_front.bind("<Button-1>", lambda e: self._open_preview_image("front"))
        self.lbl_thumb_front_desc = ctk.CTkLabel(f_box, text="正面原图/切片", font=ctk.CTkFont(size=11), text_color="#94a3b8")
        self.lbl_thumb_front_desc.pack()

        # 反面预览
        b_box = ctk.CTkFrame(thumb_bar, fg_color="transparent")
        b_box.pack(side="left", padx=6, pady=6)
        self.lbl_thumb_back = tk.Label(b_box, text="未选反面", width=16, height=5, bg="#1e293b", fg="#94a3b8", cursor="hand2", relief="flat")
        self.lbl_thumb_back.pack(pady=(0, 2))
        self.lbl_thumb_back.bind("<Button-1>", lambda e: self._open_preview_image("back"))
        self.lbl_thumb_back_desc = ctk.CTkLabel(b_box, text="反面原图/切片", font=ctk.CTkFont(size=11), text_color="#94a3b8")
        self.lbl_thumb_back_desc.pack()

        # 头像预览
        av_box = ctk.CTkFrame(thumb_bar, fg_color="transparent")
        av_box.pack(side="left", padx=6, pady=6)
        self.lbl_thumb_avatar = tk.Label(av_box, text="暂无头像", width=9, height=5, bg="#1e293b", fg="#94a3b8", cursor="hand2", relief="flat")
        self.lbl_thumb_avatar.pack(pady=(0, 2))
        self.lbl_thumb_avatar.bind("<Button-1>", lambda e: self._open_preview_image("avatar"))
        self.lbl_thumb_avatar_desc = ctk.CTkLabel(av_box, text="免冠头像", font=ctk.CTkFont(size=11), text_color="#94a3b8")
        self.lbl_thumb_avatar_desc.pack()

        tip_box = ctk.CTkFrame(thumb_bar, fg_color="transparent")
        tip_box.pack(side="right", padx=12, pady=10)
        ctk.CTkLabel(tip_box, text="💡 点击图片可在\n系统查看器中放大", font=ctk.CTkFont(size=11), text_color="#64748b", justify="center").pack()

        # 字段编辑区
        b_form_scroll = ctk.CTkScrollableFrame(right_pane, fg_color="transparent")
        b_form_scroll.pack(fill="both", expand=True, padx=12, pady=(2, 6))

        self.b_entries = {}
        for key, label in FORM_FIELDS:
            row = ctk.CTkFrame(b_form_scroll, fg_color="transparent")
            row.pack(fill="x", pady=2)
            lbl = ctk.CTkLabel(row, text=label + ":", width=80, anchor="e", font=ctk.CTkFont(size=12), text_color="#94a3b8")
            lbl.pack(side="left", padx=(0, 8))
            e = ctk.CTkEntry(row, height=28, font=ctk.CTkFont(size=12), fg_color="#0f172a", border_color="#334155")
            e.pack(side="left", fill="x", expand=True)
            self.b_entries[key] = e

        # 2.3 底部导出与扫描件综合工具栏
        b_bottom = ctk.CTkFrame(parent, fg_color="#131d2e", corner_radius=10, border_width=1, border_color="#1e293b")
        b_bottom.pack(fill="x", padx=0, pady=(8, 0))

        btn_b_excel = ctk.CTkButton(b_bottom, text="📊 导出 Excel 汇总", fg_color="#f59e0b", hover_color="#d97706", height=34, command=self.export_batch_excel)
        btn_b_excel.pack(side="left", padx=(12, 6), pady=8)

        btn_b_merge = ctk.CTkButton(b_bottom, text="📑 邮件合并套打 (合并为一个Word/Excel)", font=ctk.CTkFont(weight="bold"), fg_color="#0284c7", hover_color="#0369a1", height=34, command=self.fill_batch_merge_template)
        btn_b_merge.pack(side="left", padx=6, pady=8)

        btn_b_fill = ctk.CTkButton(b_bottom, text="📄 一人一份独立套打", fg_color="#334155", hover_color="#475569", height=34, command=self.fill_batch_templates)
        btn_b_fill.pack(side="left", padx=6, pady=8)

        btn_b_scan = ctk.CTkButton(
            b_bottom, 
            text="🖨️ 生成 A4 扫描/复印件 (彩色/黑白/单人/多页PDF)", 
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#8b5cf6", 
            hover_color="#7c3aed", 
            height=34, 
            command=self.open_batch_scan_dialog
        )
        btn_b_scan.pack(side="right", padx=(6, 12), pady=8)

    # ====== 3. 模板智能管理工作台 ======

    def _build_template_tab(self, parent):
        t_frame = ctk.CTkFrame(parent, fg_color="#131d2e", corner_radius=10, border_width=1, border_color="#1e293b")
        t_frame.pack(fill="both", expand=True, padx=0, pady=0)

        ctk.CTkLabel(t_frame, text="🏷️ 模板占位符制作指南", font=ctk.CTkFont(size=15, weight="bold"), text_color="#f8fafc").pack(anchor="w", padx=20, pady=(16, 8))

        desc = (
            "在您的 Word (.docx) 或 Excel (.xlsx) 表格/合同中插入以下占位符，套打时会自动提取填充：\n\n"
            "【文字占位符】\n"
            "  {{姓名}}        {{性别}}        {{民族}}        {{出生日期}}        {{年龄}}\n"
            "  {{身份证号码}}    {{住址}}        {{签发机关}}    {{有效期限}}\n\n"
            "【照片/图片占位符 (Word 模板)】\n"
            "  {{头像}} 或 {{照片}}   —— 自动纠正卡面并精准切取二代证免冠一寸头像！\n"
            "  {{正面照片}} 或 {{正面}} —— 自动将矫正摆正、带有标准圆角的身份证正面贴入！\n"
            "  {{反面照片}} 或 {{反面}} —— 自动将矫正摆正、带有标准圆角的身份证国徽面贴入！\n\n"
            "【A4 扫描件与复印件功能】\n"
            "  - 自动检测倾斜并透视矫正，严格依照 85.6mm x 54.0mm 实际身份证尺寸。\n"
            "  - A4 纸张排版：上面放正面，下面放背面，支持彩色高清扫描件与黑白复印件。\n"
            "  - 支持一键导出一人一份独立 PDF / JPG，或多人合并为一个连续多页 PDF。"
        )
        ctk.CTkLabel(t_frame, text=desc, font=ctk.CTkFont(family="Consolas", size=13), justify="left", text_color="#38bdf8").pack(anchor="w", padx=20, pady=6)

        ctk.CTkButton(t_frame, text="📁 打开本地模板存放文件夹 (user_templates)", fg_color="#334155", hover_color="#475569", height=34, command=lambda: os.startfile(USER_TEMPLATES_DIR)).pack(anchor="w", padx=20, pady=14)

    # ====== 授权业务逻辑 (严格依据 SDK 属性呈现，杜绝主观夸张用语) ======

    def _update_auth_ui(self):
        status = auth_manager.get_status()
        if status["is_valid"]:
            exp_text = status.get("expire_at") or ("永久" if status.get("is_perpetual") else f"{status.get('remaining_days')}天")
            self.auth_badge_btn.configure(
                text=f"● 授权有效 ({exp_text})",
                fg_color="#1e293b",
                hover_color="#334155",
                text_color="#34d399",
                border_color="#334155"
            )
        else:
            self.auth_badge_btn.configure(
                text="○ 未激活 (点击激活)",
                fg_color="#1e293b",
                hover_color="#334155",
                text_color="#fbbf24",
                border_color="#475569"
            )

    def open_auth_dialog(self):
        dialog = ctk.CTkToplevel(self) if USE_CTK else tk.Toplevel(self)
        dialog.title("软件许可证与设备信息")
        dialog.geometry("520x460")
        dialog.resizable(False, False)
        dialog.grab_set()

        status = auth_manager.get_status()
        is_active = status.get("is_valid", False)

        ctk.CTkLabel(dialog, text="软件许可证与设备信息", font=ctk.CTkFont(size=16, weight="bold"), text_color="#f8fafc").pack(pady=(16, 6))

        # 授权档案卡 (直接使用 SDK 返回的原生属性)
        card = ctk.CTkFrame(dialog, fg_color="#131d2e", corner_radius=8, border_width=1, border_color="#1e293b")
        card.pack(fill="x", padx=24, pady=6)

        # 1. 产品名称
        p_name = status.get("product_name") or "身份证信息提取工具"
        p_id = status.get("product_id") or "-"
        row_p = ctk.CTkFrame(card, fg_color="transparent")
        row_p.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(row_p, text="授权产品:", width=80, anchor="w", font=ctk.CTkFont(size=12), text_color="#94a3b8").pack(side="left")
        ctk.CTkLabel(row_p, text=f"{p_name} ({p_id})", font=ctk.CTkFont(size=12, weight="bold"), text_color="#f1f5f9").pack(side="left")

        # 2. 授权状态与有效期限
        exp_text = status.get("expire_at") or ("永久有效" if status.get("is_perpetual") else f"剩余 {status.get('remaining_days')} 天")
        st_desc = f"有效 ({exp_text})" if is_active else f"未激活 ({status.get('message', '无有效许可证')})"
        st_color = "#34d399" if is_active else "#f59e0b"

        row_st = ctk.CTkFrame(card, fg_color="transparent")
        row_st.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row_st, text="授权状态:", width=80, anchor="w", font=ctk.CTkFont(size=12), text_color="#94a3b8").pack(side="left")
        ctk.CTkLabel(row_st, text=st_desc, font=ctk.CTkFont(size=12, weight="bold"), text_color=st_color).pack(side="left")

        # 3. 许可证序列号
        lic_id = status.get("license_id") or ("已绑定本地许可证" if is_active else "无")
        row_lic = ctk.CTkFrame(card, fg_color="transparent")
        row_lic.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row_lic, text="许可证号:", width=80, anchor="w", font=ctk.CTkFont(size=12), text_color="#94a3b8").pack(side="left")
        ctk.CTkLabel(row_lic, text=str(lic_id), font=ctk.CTkFont(family="Consolas", size=12), text_color="#38bdf8" if is_active else "#64748b").pack(side="left")

        # 4. 设备硬件码 (支持一键复制)
        row_hw = ctk.CTkFrame(card, fg_color="transparent")
        row_hw.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row_hw, text="设备硬件码:", width=80, anchor="w", font=ctk.CTkFont(size=12), text_color="#94a3b8").pack(side="left")
        ctk.CTkLabel(row_hw, text=auth_manager.machine_code, font=ctk.CTkFont(family="Consolas", size=12), text_color="#f1f5f9").pack(side="left")

        def copy_hwid_act():
            self.clipboard_clear()
            self.clipboard_append(auth_manager.machine_code)
            messagebox.showinfo("已复制", f"设备硬件码已复制到剪贴板：\n{auth_manager.machine_code}")

        ctk.CTkButton(row_hw, text="复制", width=50, height=22, font=ctk.CTkFont(size=11), fg_color="#334155", hover_color="#475569", command=copy_hwid_act).pack(side="right")

        # 5. 已启用的功能特性
        feats = status.get("features", [])
        feats_str = ", ".join(feats) if feats else ("标准功能集 (OCR/校正/扫描件/套打)" if is_active else "未启用")
        row_f = ctk.CTkFrame(card, fg_color="transparent")
        row_f.pack(fill="x", padx=16, pady=(4, 12))
        ctk.CTkLabel(row_f, text="已启功能:", width=80, anchor="w", font=ctk.CTkFont(size=12), text_color="#94a3b8").pack(side="left")
        ctk.CTkLabel(row_f, text=feats_str, font=ctk.CTkFont(size=11), text_color="#94a3b8").pack(side="left")

        # 3. 授权码输入与升级/更新操作区
        act_box = ctk.CTkFrame(dialog, fg_color="transparent")
        act_box.pack(fill="x", padx=24, pady=(8, 4))

        input_title = "更新 / 升级授权码 (支持输入新卡密升级功能):" if is_active else "请输入授权激活码:"
        ctk.CTkLabel(act_box, text=input_title, font=ctk.CTkFont(size=12), text_color="#38bdf8" if is_active else "#94a3b8").pack(anchor="w", pady=(0, 4))

        placeholder = "输入新卡密可直接更新或升级授权..." if is_active else "格式如: 1234-5678-ABCD-EF01"
        code_entry = ctk.CTkEntry(
            act_box, 
            placeholder_text=placeholder, 
            height=36, 
            font=ctk.CTkFont(family="Consolas", size=13),
            border_color="#334155"
        )
        code_entry.pack(fill="x")

        def do_act():
            code = code_entry.get().strip()
            if not code:
                messagebox.showwarning("提示", "请输入授权码！")
                return
            ok, msg = auth_manager.activate_online(code)
            if ok:
                action_word = "授权更新成功" if is_active else "激活成功"
                messagebox.showinfo("成功", f"{action_word}！\n{msg}")
                self._update_auth_ui()
                dialog.destroy()
            else:
                messagebox.showerror("失败", f"验证未通过: {msg}")

        def do_unbind():
            # 本机已激活状态下无需强制输入卡密，支持直接解绑，或传硬件码/许可证号/新卡密
            ident = code_entry.get().strip()
            lic_no = status.get('license_id') or '本地许可证'
            confirm_msg = (
                f"确定要解除当前设备的绑定授权吗？\n\n"
                f"• 设备硬件码: {auth_manager.machine_code}\n"
                f"• 许可证编号: {lic_no}\n\n"
                f"解绑后本机将恢复未激活状态，授权配额将释放，可迁移至新设备激活使用。"
            )
            if not messagebox.askyesno("确认解绑", confirm_msg):
                return

            ok, msg = auth_manager.unbind_online(ident)
            if ok:
                messagebox.showinfo("解绑成功", "已成功解除当前设备授权！\n授权配额已释放，随时可在新电脑上激活使用。")
                self._update_auth_ui()
                dialog.destroy()
            else:
                res = messagebox.askyesno("解绑提示", f"服务器返回: {msg}\n\n是否直接强制清理本机的离线授权凭据？\n(清理后本机将立即恢复未激活状态)")
                if res:
                    for p in [auth_manager.license_file, auth_manager.token_file]:
                        if os.path.exists(p):
                            try: os.remove(p)
                            except: pass
                    messagebox.showinfo("已清除", "本机授权凭证已清除，已恢复未激活状态。")
                    self._update_auth_ui()
                    dialog.destroy()

        btn_act_text = "验证并更新授权" if is_active else "验证并激活"
        btn_act = ctk.CTkButton(dialog, text=btn_act_text, fg_color="#2563eb", hover_color="#1d4ed8", height=36, font=ctk.CTkFont(weight="bold"), command=do_act)
        btn_act.pack(fill="x", padx=24, pady=(8, 4))

        if is_active:
            btn_unbind = ctk.CTkButton(dialog, text="解绑此设备授权 (换机时使用)", fg_color="transparent", text_color="#94a3b8", hover_color="#1e293b", command=do_unbind)
            btn_unbind.pack(pady=2)

    def _check_auth_or_prompt(self) -> bool:
        is_valid, msg, _ = auth_manager.verify_local_license()
        if not is_valid:
            res = messagebox.askyesno("商业版激活提示", f"该功能需要商业授权解锁！\n状态: {msg}\n\n是否立即输入卡密进行激活？")
            if res:
                self.open_auth_dialog()
            return False
        return True

    # ====== 单图识别与精准卡面切片 ======

    def _reset_single_ocr_buttons(self):
        """恢复单图识别按钮的可用状态与默认文本 (防止卡在'正在全量切片...'状态)"""
        try:
            if hasattr(self, "btn_run_fast_ocr") and self.btn_run_fast_ocr.winfo_exists():
                self.btn_run_fast_ocr.configure(state="normal", text="⚡ 快速提取 (纯 OCR)")
            if hasattr(self, "btn_run_full_ocr") and self.btn_run_full_ocr.winfo_exists():
                self.btn_run_full_ocr.configure(state="normal", text="📸 完整识别 (含切片)")
        except Exception:
            pass

    def select_front_image(self):
        f = filedialog.askopenfilename(
            title="选择正面、单图双面图片或单页PDF", 
            filetypes=[
                ("支持格式 (单图/单页PDF)", "*.jpg;*.jpeg;*.png;*.bmp;*.pdf"), 
                ("常用图片", "*.jpg;*.jpeg;*.png;*.bmp"), 
                ("单页PDF文档", "*.pdf")
            ]
        )
        if f:
            ext = os.path.splitext(f)[1].lower()
            if ext == ".pdf":
                pages = render_pdf_to_images(f)
                if not pages:
                    messagebox.showerror("错误", "无法解析该 PDF 文件！")
                    return
                if len(pages) > 1:
                    messagebox.showwarning(
                        "多页文档提示",
                        f"检测到该 PDF 包含 {len(pages)} 页（属于多页文档）。\n\n"
                        f"【📷 单图高精度识别】专用于处理单张图片或单页PDF（如一页包含正反两面）；\n"
                        f"多页文档或多人材料请切换至顶部【📁 批量分组套打与扫描件】功能处理！"
                    )
                    return
                self.front_path = pages[0]
                self.front_btn.configure(text=f"已选单页PDF (含正反面):\n{os.path.basename(f)}")
            else:
                self.front_path = f
                self.front_btn.configure(text=f"已选正面/双面图:\n{os.path.basename(f)}")
            # 重新选择图片后立即复位识别按钮状态
            self._reset_single_ocr_buttons()

    def select_back_image(self):
        f = filedialog.askopenfilename(
            title="选择反面图片或单页PDF", 
            filetypes=[
                ("支持格式 (单图/单页PDF)", "*.jpg;*.jpeg;*.png;*.bmp;*.pdf"), 
                ("常用图片", "*.jpg;*.jpeg;*.png;*.bmp"), 
                ("单页PDF文档", "*.pdf")
            ]
        )
        if f:
            ext = os.path.splitext(f)[1].lower()
            if ext == ".pdf":
                pages = render_pdf_to_images(f)
                if not pages:
                    messagebox.showerror("错误", "无法解析该 PDF 文件！")
                    return
                if len(pages) > 1:
                    messagebox.showwarning(
                        "多页文档提示",
                        f"检测到该 PDF 包含 {len(pages)} 页（属于多页文档）。\n\n"
                        f"【📷 单图高精度识别】专用于处理单张图片或单页PDF；\n"
                        f"多页文档或多人材料请切换至顶部【📁 批量分组套打与扫描件】功能处理！"
                    )
                    return
                self.back_path = pages[0]
                self.back_btn.configure(text=f"已选单页PDF反面:\n{os.path.basename(f)}")
            else:
                self.back_path = f
                self.back_btn.configure(text=f"已选反面:\n{os.path.basename(f)}")
            # 重新选择图片后立即复位识别按钮状态
            self._reset_single_ocr_buttons()

    def clear_images(self):
        self.front_path = ""
        self.back_path = ""
        self.avatar_path = ""
        self.current_data = {}
        self.front_btn.configure(text="🖼️ 点击选择【正面 (人像面)】图片\n(支持单图正反合照自动拆分)")
        self.back_btn.configure(text="🖼️ 点击选择【反面 (国徽面)】图片 (可选)")
        for entry in self.form_entries.values():
            entry.delete(0, "end")
        self.warn_lbl.configure(text="")
        self.avatar_photo_image = None
        self.avatar_display.configure(image="", text="识别正面后\n自动切取免冠头像")
        # 重选图片时立即无条件恢复按钮状态
        self._reset_single_ocr_buttons()

    def run_single_ocr(self, with_crop: bool = False):
        if not self._check_auth_or_prompt():
            return
        if not self.front_path and not self.back_path:
            messagebox.showwarning("提示", "请先选择身份证图片！")
            return

        self.btn_run_fast_ocr.configure(state="disabled")
        self.btn_run_full_ocr.configure(state="disabled")
        if with_crop:
            self.btn_run_full_ocr.configure(text="正在全量切片...")
        else:
            self.btn_run_fast_ocr.configure(text="正在极速提取...")

        def _worker():
            try:
                front_lines = ocr_image(self.front_path) if self.front_path else []
                back_lines = ocr_image(self.back_path) if self.back_path else []

                if not front_lines and not back_lines:
                    if not check_ocr_service():
                        self.after(0, lambda: messagebox.showerror(
                            "本地OCR引擎未就绪",
                            "当前尚未安装本地离线 OCR 识别引擎！\n\n【一键解决】\n请在终端执行安装纯本地推理库：\npip install rapidocr-onnxruntime\n\n安装完成后无需启动任何额外软件，即可直接离线识别！"
                        ))
                    else:
                        self.after(0, lambda: messagebox.showwarning("提示", "未能从图片中识别到身份证文字，请确认图片清晰、平整且无遮挡。"))
                    self.after(0, self._reset_single_ocr_buttons)
                    return

                side = ""
                if self.front_path and not self.back_path:
                    data, side = parse_single_image(front_lines)
                elif not self.front_path and self.back_path:
                    data, side = parse_single_image(back_lines)
                else:
                    data = parse_id_card(front_lines, back_lines)
                    side = "both" if (front_lines and back_lines) else ""

                # 图像切片处理 (仅在 with_crop=True 时执行)
                target_front = self.front_path if self.front_path else (self.back_path if not self.front_path else "")
                raw_ref = target_front or self.back_path or "default"
                name_clean = re.sub(r'[\\/*?:\[\]]', '', str(data.get("name") or "单人"))
                uid = hashlib.md5(raw_ref.encode("utf-8", errors="ignore")).hexdigest()[:6]

                cards_dir = os.path.join(OUTPUT_DIR, "cards")
                avatars_dir = os.path.join(OUTPUT_DIR, "avatars")
                if with_crop:
                    os.makedirs(cards_dir, exist_ok=True)
                    os.makedirs(avatars_dir, exist_ok=True)

                card_front = None
                saved_front_card = ""
                saved_back_card = ""
                avatar_img = None
                saved_avatar = ""

                if with_crop:
                    # 模式 A：单图同时包含正反两面 (一图双面)
                    if self.front_path and not self.back_path and side == "both":
                        card_front, card_back = crop_both_sides_from_single_image(self.front_path, mode="color")
                        if card_front:
                            saved_front_card = os.path.join(cards_dir, f"front_{name_clean}_{uid}.png")
                            card_front.save(saved_front_card, "PNG", dpi=(300, 300))
                            avatar_img = crop_avatar_from_standard_card(card_front)
                            if avatar_img:
                                saved_avatar = os.path.join(avatars_dir, f"avatar_{name_clean}_{uid}.jpg")
                                avatar_img.convert("RGB").save(saved_avatar, "JPEG", quality=95, dpi=(300, 300))
                                self.avatar_path = saved_avatar
                        if card_back:
                            saved_back_card = os.path.join(cards_dir, f"back_{name_clean}_{uid}.png")
                            card_back.save(saved_back_card, "PNG", dpi=(300, 300))
                    else:
                        # 模式 B：常规单张或分开的两张
                        if target_front:
                            card_front = correct_and_crop_card(target_front, mode="color")
                            if card_front:
                                saved_front_card = os.path.join(cards_dir, f"front_{name_clean}_{uid}.png")
                                card_front.save(saved_front_card, "PNG", dpi=(300, 300))
                                avatar_img = crop_avatar_from_standard_card(card_front)
                                if avatar_img:
                                    saved_avatar = os.path.join(avatars_dir, f"avatar_{name_clean}_{uid}.jpg")
                                    avatar_img.convert("RGB").save(saved_avatar, "JPEG", quality=95, dpi=(300, 300))
                                    self.avatar_path = saved_avatar

                        if self.back_path:
                            card_back = correct_and_crop_card(self.back_path, mode="color")
                            if card_back:
                                saved_back_card = os.path.join(cards_dir, f"back_{name_clean}_{uid}.png")
                                card_back.save(saved_back_card, "PNG", dpi=(300, 300))
                else:
                    self.avatar_path = ""

                self.current_data = data
                self.current_data["avatar_path"] = saved_avatar
                self.current_data["front_image_path"] = saved_front_card or self.front_path
                self.current_data["back_image_path"] = saved_back_card or self.back_path

                def _update():
                    try:
                        for k, entry in self.form_entries.items():
                            entry.delete(0, "end")
                            val = data.get(k, "")
                            if val is not None:
                                entry.insert(0, str(val))

                        if avatar_img:
                            thumb = avatar_img.copy()
                            thumb.thumbnail((100, 125))
                            tw, th = thumb.size
                            if USE_CTK:
                                self.avatar_photo_image = ctk.CTkImage(light_image=thumb, dark_image=thumb, size=(tw, th))
                            else:
                                self.avatar_photo_image = ImageTk.PhotoImage(thumb)
                            self.avatar_display.configure(image=self.avatar_photo_image, text="")
                        else:
                            self.avatar_display.configure(image="", text="⚡ 快速提取模式\n未生成免冠头像")

                        warns = []
                        id_num = data.get("id_number", "")
                        if id_num and not validate_id(id_num):
                            warns.append("身份证号码校验位不合法或格式错误")

                        self.warn_lbl.configure(text="⚠️ " + "；".join(warns) if warns else "")

                        if with_crop:
                            messagebox.showinfo("完成", "身份证识别与高清卡片切片完成！免冠头像已就绪。")
                        else:
                            messagebox.showinfo("完成", "⚡ 身份证文字已极速提取完毕！\n(当前为纯文字模式，若需头像或卡片请点击【完整识别】)")
                    finally:
                        self._reset_single_ocr_buttons()

                self.after(0, _update)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("错误", f"识别异常: {e}"))
                self.after(0, self._reset_single_ocr_buttons)

        threading.Thread(target=_worker, daemon=True).start()

    def export_single_a4_scan(self):
        """单人生成 A4 扫描件 (支持自适应切片与防盗防挪用水印)"""
        if not self._check_auth_or_prompt():
            return

        front_p = self.current_data.get("front_image_path") or self.front_path or ""
        back_p = self.current_data.get("back_image_path") or self.back_path or ""

        if not front_p and not back_p:
            messagebox.showwarning("提示", "未找到身份证图片，请先在左侧选择或导入身份证正面/反面图片！")
            return

        name = self.form_entries["name"].get().strip() or "身份证扫描件"

        dialog = ctk.CTkToplevel(self) if USE_CTK else tk.Toplevel(self)
        dialog.title("单人 A4 标准扫描件导出设置")
        dialog.geometry("480x430")
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.attributes("-topmost", True)
        dialog.after(10, dialog.lift)
        dialog.after(20, dialog.focus_force)

        ctk.CTkLabel(dialog, text="🖨️ A4 身份证扫描件导出设置", font=ctk.CTkFont(size=15, weight="bold"), text_color="#f8fafc").pack(pady=(14, 4))

        box = ctk.CTkFrame(dialog, fg_color="#1e293b", corner_radius=10)
        box.pack(fill="x", padx=20, pady=6)

        # 1. 色彩与质感
        ctk.CTkLabel(box, text="色彩与效果模式:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8").pack(anchor="w", padx=14, pady=(8, 2))
        mode_var = tk.StringVar(value="color")
        f_row = ctk.CTkFrame(box, fg_color="transparent")
        f_row.pack(fill="x", padx=14, pady=2)
        ctk.CTkRadioButton(f_row, text="🎨 高清彩色扫描件", variable=mode_var, value="color").pack(side="left", padx=(6, 20))
        ctk.CTkRadioButton(f_row, text="🖤 经典黑白复印件", variable=mode_var, value="bw").pack(side="left")

        # 2. 输出格式
        ctk.CTkLabel(box, text="保存格式:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8").pack(anchor="w", padx=14, pady=(8, 2))
        fmt_var = tk.StringVar(value="pdf")
        fmt_row = ctk.CTkFrame(box, fg_color="transparent")
        fmt_row.pack(fill="x", padx=14, pady=2)
        ctk.CTkRadioButton(fmt_row, text="📑 A4 标准 PDF 文档 (*.pdf)", variable=fmt_var, value="pdf").pack(side="left", padx=(6, 20))
        ctk.CTkRadioButton(fmt_row, text="🖼️ 高清 JPG 图片 (*.jpg)", variable=fmt_var, value="jpg").pack(side="left")

        # 3. 防盗防挪用水印
        ctk.CTkLabel(box, text="🛡️ 防盗防挪用倾斜半透明水印 (政务/银行合规规范):", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8").pack(anchor="w", padx=14, pady=(10, 2))

        wm_enable_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(box, text="开启防伪防盗用水印 (倾斜覆盖在卡面上，防抠图盗用)", variable=wm_enable_var, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=16, pady=3)

        wm_entry = ctk.CTkEntry(box, placeholder_text="请输入水印文字...", height=30, font=ctk.CTkFont(size=12))
        wm_entry.insert(0, "仅供办理业务使用 他用无效")
        wm_entry.pack(fill="x", padx=14, pady=4)

        # 快捷模板标签
        tag_row = ctk.CTkFrame(box, fg_color="transparent")
        tag_row.pack(fill="x", padx=14, pady=(2, 10))
        ctk.CTkLabel(tag_row, text="快捷文字:", font=ctk.CTkFont(size=11), text_color="#94a3b8").pack(side="left", padx=(0, 6))

        def set_wm(t):
            wm_entry.delete(0, "end")
            wm_entry.insert(0, t)

        for tag_text, tag_val in [
            ("银行开户", "仅供办理开户业务使用 他用无效"),
            ("入职建档", "仅供入职建档使用 复印无效"),
            ("资质审核", "仅供资质审核备案使用 他用无效")
        ]:
            ctk.CTkButton(
                tag_row,
                text=tag_text,
                height=22,
                font=ctk.CTkFont(size=10),
                fg_color="#334155",
                hover_color="#475569",
                command=lambda v=tag_val: set_wm(v)
            ).pack(side="left", padx=3)

        def _do_single_export():
            # 必须在销毁窗口前安全获取所有输入值，杜绝 TclError
            m = mode_var.get()
            fmt = fmt_var.get()
            wm_text = wm_entry.get().strip() if wm_enable_var.get() else ""
            dialog.destroy()

            def _worker():
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                ext = ".pdf" if fmt == "pdf" else ".jpg"
                out_file = os.path.join(OUTPUT_DIR, "scans", f"{name}_A4扫描件_{timestamp}{ext}")
                os.makedirs(os.path.dirname(out_file), exist_ok=True)

                try:
                    cf = None
                    cb = None

                    # 1. 判断是否为一图双面
                    side_mode = getattr(self, "side_var", None)
                    is_both_side = (side_mode and side_mode.get() == "both") or (front_p and not back_p and "both" in front_p.lower())

                    if is_both_side and front_p:
                        cf, cb = crop_both_sides_from_single_image(front_p, mode=m)
                    else:
                        def _prepare_card(p, mode_str):
                            if not p or not os.path.exists(p):
                                return None
                            # 若已有切片卡片
                            if ("front_" in os.path.basename(p).lower() or "back_" in os.path.basename(p).lower()) and p.lower().endswith((".png", ".jpg")):
                                try:
                                    im = Image.open(p)
                                    if mode_str == "bw":
                                        return convert_card_to_photocopy(im)
                                    if im.mode == "RGBA":
                                        bg = Image.new("RGB", im.size, (255, 255, 255))
                                        bg.paste(im, mask=im.split()[3])
                                        return bg
                                    return im.convert("RGB")
                                except Exception:
                                    pass
                            # 现场检测切片
                            return correct_and_crop_card(p, mode=mode_str)

                        if front_p:
                            cf = _prepare_card(front_p, m)
                        if back_p:
                            cb = _prepare_card(back_p, m)

                    sheet = generate_a4_scanned_page(cf, cb, mode=m, watermark_text=wm_text)

                    if fmt == "pdf":
                        export_a4_sheets_to_pdf([sheet], out_file)
                    else:
                        sheet.save(out_file, "JPEG", quality=95, dpi=(300, 300))

                    def _on_success():
                        res = messagebox.askyesno("成功", f"A4 标准扫描件已生成：\n{out_file}\n\n是否立即打开查看？")
                        if res:
                            os.startfile(out_file)

                    self.after(0, _on_success)
                except Exception as e:
                    err_msg = str(e)
                    self.after(0, lambda: messagebox.showerror("失败", f"生成 A4 扫描件失败: {err_msg}"))

            threading.Thread(target=_worker, daemon=True).start()

        btn_run = ctk.CTkButton(
            dialog,
            text="🚀 立即生成 A4 扫描件",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#8b5cf6",
            hover_color="#7c3aed",
            height=36,
            command=_do_single_export
        )
        btn_run.pack(fill="x", padx=20, pady=(6, 10))

    def copy_avatar_image(self):
        if not self.avatar_path or not os.path.exists(self.avatar_path):
            messagebox.showinfo("提示", "当前为快速提取模式，未切取免冠头像。\n如需头像，请直接点击【📸 完整识别 (含切片)】。")
            return
        im = Image.open(self.avatar_path)
        if copy_image_to_clipboard(im):
            messagebox.showinfo("已复制", "免冠头像已复制到剪贴板！可直接按 Ctrl+V 粘贴。")
        else:
            messagebox.showerror("失败", "复制头像失败！")

    def save_avatar_image(self):
        if not self.avatar_path or not os.path.exists(self.avatar_path):
            messagebox.showinfo("提示", "当前为快速提取模式，未切取免冠头像。\n如需头像，请直接点击【📸 完整识别 (含切片)】。")
            return

        name = self.form_entries["name"].get().strip() or "身份证头像"
        save_file = filedialog.asksaveasfilename(initialfile=f"{name}_免冠头像.jpg", defaultextension=".jpg", filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png")])
        if save_file:
            shutil.copy2(self.avatar_path, save_file)
            messagebox.showinfo("成功", f"头像已保存至：\n{save_file}")

    def export_single_excel(self):
        if not self._check_auth_or_prompt():
            return
        if not self.form_entries["name"].get():
            messagebox.showwarning("提示", "请先提取身份证数据！")
            return
        row_data = {k: entry.get().strip() for k, entry in self.form_entries.items()}
        out_file = os.path.join(OUTPUT_DIR, f"身份证台账_{datetime.now().strftime('%Y%m%d')}.xlsx")
        write_to_excel(row_data, out_file)
        res = messagebox.askyesno("成功", f"数据已追加写入 Excel：\n{out_file}\n\n是否立即打开查看？")
        if res:
            os.startfile(out_file)

    def fill_single_template(self):
        if not self._check_auth_or_prompt():
            return
        tmpl_file = filedialog.askopenfilename(initialdir=USER_TEMPLATES_DIR, title="选择套打模板", filetypes=[("模板文件", "*.docx;*.xlsx")])
        if not tmpl_file:
            return

        row_data = {k: entry.get().strip() for k, entry in self.form_entries.items()}
        row_data["avatar_path"] = self.current_data.get("avatar_path") or self.avatar_path
        row_data["front_image_path"] = self.current_data.get("front_image_path") or self.front_path
        row_data["back_image_path"] = self.current_data.get("back_image_path") or self.back_path

        name = row_data.get("name") or "未命名"
        ext = os.path.splitext(tmpl_file)[1]
        out_file = os.path.join(OUTPUT_DIR, f"{name}_套打结果{ext}")

        try:
            fill_template(tmpl_file, row_data, out_file)
            res = messagebox.askyesno("成功", f"模板套打已生成：\n{out_file}\n\n是否立即打开查看？")
            if res:
                os.startfile(out_file)
        except Exception as e:
            messagebox.showerror("失败", f"模板填充失败: {e}")

    # ====== 批量操作与核对修改 (需求 2.a) ======

    def _refresh_batch_groups(self):
        """根据当前导入的素材路径，自适应解析并分组（智能兼容常规图片与多页/单页PDF）"""
        self.batch_groups.clear()

        all_items = list(self.batch_files_map.keys())
        if all_items:
            self.batch_groups = auto_group_items(all_items)

        # 刷新左栏 Treeview
        for item in self.batch_tree.get_children():
            self.batch_tree.delete(item)

        total_files = len(self.batch_files_map)
        total_people = len(self.batch_groups)
        self.batch_stats_lbl.configure(text=f"共 {total_files} 份素材 · 归属 {total_people} 位人员")

        for idx, (grp_name, fpaths) in enumerate(self.batch_groups.items(), 1):
            # 获取该组识别状态
            res = next((r for r in self.batch_results if r.get("_group_name") == grp_name), None)
            st_text = f"✅ 已识别 ({res.get('name', '-')})" if res else "待识别"
            self.batch_tree.insert("", "end", iid=grp_name, values=(
                idx,
                grp_name,
                f"{len(fpaths)} 页/张",
                st_text
            ))

    def _select_all_batch_tree(self, event=None):
        """Ctrl+A 全选批量列表条目"""
        items = self.batch_tree.get_children()
        if items:
            self.batch_tree.selection_set(items)
        return "break"

    def _on_batch_tree_selected(self, event):
        """点击左侧人员列表项，右侧联动展示详细档案支持就地修改；支持多选友好处理"""
        sel = self.batch_tree.selection()
        if not sel:
            return

        # 多选状态处理 (选择多项时不锁定某单个人员的编辑，避免数据覆盖)
        if len(sel) > 1:
            self.current_selected_group = None
            self.r_person_title.configure(text=f"👥 当前已多选 {len(sel)} 位人员 (可按【Delete】或点击【移除所选】批量移除)")
            for entry in self.b_entries.values():
                entry.delete(0, "end")
            self.lbl_thumb_front.configure(image="", text="多选状态")
            self.lbl_thumb_front.image = None
            self.lbl_thumb_front_desc.configure(text="已选择多项")
            self.lbl_thumb_back.configure(image="", text="多选状态")
            self.lbl_thumb_back.image = None
            self.lbl_thumb_back_desc.configure(text="已选择多项")
            self.lbl_thumb_avatar.configure(image="", text="多选状态")
            self.lbl_thumb_avatar.image = None
            self.lbl_thumb_avatar_desc.configure(text="已选择多项")
            return

        grp_name = sel[0]
        self.current_selected_group = grp_name
        self.r_person_title.configure(text=f"👤 当前核对人员: 【{grp_name}】")

        # 查找该组已有识别结果或默认值
        res = next((r for r in self.batch_results if r.get("_group_name") == grp_name), None)
        fpaths = self.batch_groups.get(grp_name, [])

        # 填充表单
        for key, entry in self.b_entries.items():
            entry.delete(0, "end")
            if res and res.get(key) is not None:
                entry.insert(0, str(res.get(key)))
            elif key == "name" and not res:
                entry.insert(0, grp_name)

        # 刷新右侧切片缩略图
        self._update_batch_thumbnails(res, fpaths)

    def _open_preview_image(self, which: str):
        """点击缩略图调用系统图片查看器全屏放大高清原图或切片"""
        target = ""
        if which == "front":
            target = getattr(self, "current_preview_front_file", "")
        elif which == "back":
            target = getattr(self, "current_preview_back_file", "")
        elif which == "avatar":
            target = getattr(self, "current_preview_avatar_file", "")

        if target and os.path.exists(target):
            try:
                os.startfile(target)
            except Exception as e:
                print(f"[GUI] 打开图片失败: {e}")

    def _update_batch_thumbnails(self, res: dict | None, fpaths: list[str]):
        """
        加载右侧正面/反面/头像切片预览
        - 识别前：直接将导入的原始身份证照片作为候选正面/反面缩略图展示
        - 识别后：展示带有平滑透明圆角、已透视摆正的切片卡面与免冠头像
        """
        self.current_preview_front_file = ""
        self.current_preview_back_file = ""
        self.current_preview_avatar_file = ""

        # 默认清空并提示
        self.lbl_thumb_front.configure(image="", text="未选正面")
        self.lbl_thumb_front.image = None
        self.lbl_thumb_back.configure(image="", text="未选反面")
        self.lbl_thumb_back.image = None
        self.lbl_thumb_avatar.configure(image="", text="暂无头像")
        self.lbl_thumb_avatar.image = None

        front_file = ""
        back_file = ""
        avatar_file = ""

        if res:
            front_file = res.get("front_image_path", "")
            back_file = res.get("back_image_path", "")
            avatar_file = res.get("avatar_path", "")

        # 若尚未识别，或者路径缺失，降级从本组原始导入图片中抽取
        if not front_file and fpaths:
            front_file = fpaths[0]
        if not back_file and len(fpaths) >= 2:
            back_file = fpaths[1]

        # 1. 渲染正面预览
        if front_file and os.path.exists(front_file):
            self.current_preview_front_file = front_file
            try:
                im = Image.open(front_file)
                im.load()
                if im.mode == "RGBA":
                    bg = Image.new("RGBA", im.size, (15, 23, 42, 255))
                    im = Image.alpha_composite(bg, im).convert("RGB")
                else:
                    im = im.convert("RGB")
                im.thumbnail((125, 82))
                photo_f = ImageTk.PhotoImage(im)
                self.lbl_thumb_front.configure(image=photo_f, text="")
                self.lbl_thumb_front.image = photo_f
                desc = "✅ 正面圆角卡面" if (res and res.get("front_image_path")) else "📷 正面待识别原图"
                self.lbl_thumb_front_desc.configure(text=desc)
            except Exception as e:
                print(f"[GUI] 加载正面预览失败: {e}")
                self.lbl_thumb_front.configure(image="", text="读取失败")
                self.lbl_thumb_front.image = None
                self.lbl_thumb_front_desc.configure(text="正面损坏")
        else:
            self.lbl_thumb_front_desc.configure(text="未导入正面")

        # 2. 渲染反面预览
        if back_file and os.path.exists(back_file):
            self.current_preview_back_file = back_file
            try:
                im = Image.open(back_file)
                im.load()
                if im.mode == "RGBA":
                    bg = Image.new("RGBA", im.size, (15, 23, 42, 255))
                    im = Image.alpha_composite(bg, im).convert("RGB")
                else:
                    im = im.convert("RGB")
                im.thumbnail((125, 82))
                photo_b = ImageTk.PhotoImage(im)
                self.lbl_thumb_back.configure(image=photo_b, text="")
                self.lbl_thumb_back.image = photo_b
                desc = "✅ 反面圆角卡面" if (res and res.get("back_image_path")) else "📷 反面待识别原图"
                self.lbl_thumb_back_desc.configure(text=desc)
            except Exception as e:
                print(f"[GUI] 加载反面预览失败: {e}")
                self.lbl_thumb_back.configure(image="", text="读取失败")
                self.lbl_thumb_back.image = None
                self.lbl_thumb_back_desc.configure(text="反面损坏")
        else:
            self.lbl_thumb_back_desc.configure(text="未导入反面")

        # 3. 渲染头像预览
        if avatar_file and os.path.exists(avatar_file):
            self.current_preview_avatar_file = avatar_file
            try:
                im = Image.open(avatar_file)
                im.load()
                im = im.convert("RGB")
                im.thumbnail((70, 85))
                photo_av = ImageTk.PhotoImage(im)
                self.lbl_thumb_avatar.configure(image=photo_av, text="")
                self.lbl_thumb_avatar.image = photo_av
                self.lbl_thumb_avatar_desc.configure(text="✅ 二代证头像")
            except Exception as e:
                print(f"[GUI] 加载头像预览失败: {e}")
                self.lbl_thumb_avatar.configure(image="", text="暂无头像")
                self.lbl_thumb_avatar.image = None
                self.lbl_thumb_avatar_desc.configure(text="头像缺失")
        else:
            self.lbl_thumb_avatar_desc.configure(text="⏳ 识别后提取")

    def save_current_batch_item_edit(self):
        """需求 2.a：将右栏修改的数据就地保存进 batch_results 内存中"""
        if not self.current_selected_group:
            messagebox.showwarning("提示", "请先在左侧选择要修改的人员分组！")
            return

        grp_name = self.current_selected_group
        res = next((r for r in self.batch_results if r.get("_group_name") == grp_name), None)
        if not res:
            res = {"_group_name": grp_name}
            self.batch_results.append(res)

        # 将当前输入的每一个字段回写
        for key, entry in self.b_entries.items():
            res[key] = entry.get().strip()

        # 更新左侧树状视图展示的姓名
        new_name = res.get("name") or grp_name
        self.batch_tree.item(grp_name, values=(
            self.batch_tree.item(grp_name)["values"][0],
            grp_name,
            self.batch_tree.item(grp_name)["values"][2],
            f"✅ 已核对修改 ({new_name})"
        ))
        messagebox.showinfo("成功", f"【{new_name}】的档案数据已成功保存！\n套打与导出将自动采用最新修改。")

    def batch_add_directory(self):
        d = filedialog.askdirectory(title="选择包含身份证图片或PDF的文件夹")
        if not d:
            return
        added = 0
        for root, _, files in os.walk(d):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in SUPPORTED_IMAGE_EXTS or ext == ".pdf":
                    full_p = os.path.abspath(os.path.join(root, f))
                    if full_p not in self.batch_files_map:
                        self.batch_files_map[full_p] = {
                            "size": os.path.getsize(full_p),
                            "base_name": _extract_base_name(f)
                        }
                        added += 1
        self._refresh_batch_groups()
        if added > 0:
            messagebox.showinfo("完成", f"已成功导入 {added} 份档案素材！\n已自动探测并分组完毕。")

    def batch_add_files(self):
        files = filedialog.askopenfilenames(
            title="追加身份证图片或PDF文件", 
            filetypes=[
                ("所有支持格式", "*.jpg;*.jpeg;*.png;*.bmp;*.pdf"),
                ("身份证图片", "*.jpg;*.jpeg;*.png;*.bmp"),
                ("PDF扫描件", "*.pdf")
            ]
        )
        if not files:
            return
        added = 0
        for f in files:
            full_p = os.path.abspath(f)
            if full_p not in self.batch_files_map:
                self.batch_files_map[full_p] = {
                    "size": os.path.getsize(full_p),
                    "base_name": _extract_base_name(os.path.basename(f))
                }
                added += 1
        self._refresh_batch_groups()
        if added > 0:
            messagebox.showinfo("完成", f"已成功追加 {added} 份档案素材！\n已自动探测并分组完毕。")

    def batch_remove_selected(self):
        """支持单选或按住 Ctrl / Shift 多选后批量移除选中人员素材"""
        sel = self.batch_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先在列表中选中要移除的人员分组！\n(支持按住 Ctrl 或 Shift 键进行多选)")
            return

        groups_to_remove = list(sel)
        count = len(groups_to_remove)
        names_str = "、".join(groups_to_remove[:5])
        if count > 5:
            names_str += f" 等共 {count} 位"

        confirm_msg = f"确定要从批量列表中移除以下 {count} 位人员素材吗？\n\n{names_str}"
        if not messagebox.askyesno("确认移除", confirm_msg):
            return

        for grp_name in groups_to_remove:
            fpaths = self.batch_groups.pop(grp_name, [])
            for fp in fpaths:
                self.batch_files_map.pop(fp, None)
            self.batch_results = [r for r in self.batch_results if r.get("_group_name") != grp_name]

        # 若是 PDF 渲染出的页面，检查原 PDF 是否已无剩余页面
        remaining_fps = set()
        for fps in self.batch_groups.values():
            remaining_fps.update(fps)
        to_del = []
        for src_fp in self.batch_files_map:
            if src_fp.lower().endswith(".pdf"):
                stem = re.sub(r'[\\/*?:\[\]]', '', os.path.splitext(os.path.basename(src_fp))[0])
                if not any(stem in p for p in remaining_fps):
                    to_del.append(src_fp)
        for d in to_del:
            self.batch_files_map.pop(d, None)

        # 若当前选中的人员在被删除列表中，重置右侧表单与预览卡片
        if self.current_selected_group in groups_to_remove or not self.batch_tree.selection():
            self.current_selected_group = None
            self.r_person_title.configure(text="👤 当前选中人员档案 (选择左侧条目核对修改)")
            for entry in self.b_entries.values():
                entry.delete(0, "end")
            self.lbl_thumb_front.configure(image="", text="未选正面")
            self.lbl_thumb_front.image = None
            self.lbl_thumb_front_desc.configure(text="正面原图/切片")
            self.lbl_thumb_back.configure(image="", text="未选反面")
            self.lbl_thumb_back.image = None
            self.lbl_thumb_back_desc.configure(text="反面原图/切片")
            self.lbl_thumb_avatar.configure(image="", text="暂无头像")
            self.lbl_thumb_avatar.image = None
            self.lbl_thumb_avatar_desc.configure(text="免冠头像")

        # 刷新左栏 Treeview
        for item in self.batch_tree.get_children():
            self.batch_tree.delete(item)

        total_files = len(self.batch_files_map)
        total_people = len(self.batch_groups)
        self.batch_stats_lbl.configure(text=f"共 {total_files} 份素材 · 归属 {total_people} 位人员")

        for idx, (g_name, fps) in enumerate(self.batch_groups.items(), 1):
            res = next((r for r in self.batch_results if r.get("_group_name") == g_name), None)
            st_text = f"✅ 已识别 ({res.get('name', '-')})" if res else "待识别"
            self.batch_tree.insert("", "end", iid=g_name, values=(
                idx,
                g_name,
                f"{len(fps)} 页/张",
                st_text
            ))

    def batch_clear_all(self):
        if not self.batch_files_map:
            return
        if messagebox.askyesno("确认", "确定要清空全部人员与图片吗？"):
            self.batch_files_map.clear()
            self.batch_groups.clear()
            self.batch_results.clear()
            self.current_selected_group = None
            self._refresh_batch_groups()

    def run_batch_ocr(self, with_crop: bool = False):
        if not self._check_auth_or_prompt():
            return
        if not self.batch_groups:
            messagebox.showwarning("提示", "当前列表为空，请先导入图片或文件夹！")
            return

        total_items = len(self.batch_groups)
        self.btn_run_fast_batch.configure(state="disabled")
        self.btn_run_full_batch.configure(state="disabled")
        if with_crop:
            self.btn_run_full_batch.configure(text=f"⏳ 正在全量处理 [0/{total_items}]...")
        else:
            self.btn_run_fast_batch.configure(text=f"⏳ 正在极速识别 [0/{total_items}]...")
        self.batch_progress_bar.set(0)

        def _worker():
            results = []
            try:
                groups_list = list(self.batch_groups.items())
                for idx, (grp_name, fpaths) in enumerate(groups_list, 1):
                    # 1. 进度前置显示
                    def _step_start(i=idx, g=grp_name, fps=fpaths):
                        progress_val = (i - 1) / total_items
                        self.batch_progress_bar.set(progress_val)
                        if with_crop:
                            self.btn_run_full_batch.configure(text=f"⏳ 全量切片 [{i}/{total_items}] {g}...")
                            self.batch_stats_lbl.configure(text=f"⏳ 全量切片中 [{i}/{total_items}]: 正在处理与切片 【{g}】...")
                        else:
                            self.btn_run_fast_batch.configure(text=f"⏳ 极速识别 [{i}/{total_items}] {g}...")
                            self.batch_stats_lbl.configure(text=f"⏳ 极速识别中 [{i}/{total_items}]: 正在提取文字 【{g}】...")

                        if self.batch_tree.exists(g):
                            self.batch_tree.item(g, values=(i, g, f"{len(fps)} 张", "⏳ 处理中..."))
                            self.batch_tree.selection_set(g)
                            self.batch_tree.see(g)
                            self._on_batch_tree_selected(None)

                    self.after(0, _step_start)

                    # 2. 执行识别与切片
                    data = process_single_group(fpaths, with_crop=with_crop)
                    data["_group_name"] = grp_name
                    data["_files"] = [os.path.basename(p) for p in fpaths]
                    results.append(data)

                    # 3. 完成即时刷新
                    def _step_done(i=idx, g=grp_name, d=data, fps=fpaths):
                        real_name = d.get("name") or g
                        progress_val = i / total_items
                        self.batch_progress_bar.set(progress_val)
                        status_tag = f"✅ 已完成 (含切片)" if with_crop else f"✅ 已提取 (纯文字)"
                        if self.batch_tree.exists(g):
                            self.batch_tree.item(g, values=(i, g, f"{len(fps)} 张", f"{status_tag} · {real_name}"))
                            self.batch_tree.selection_set(g)
                            self._on_batch_tree_selected(None)

                    self.after(0, _step_done)

                self.batch_results = results

                def _finish():
                    self.batch_progress_bar.set(1.0)
                    self.btn_run_fast_batch.configure(state="normal", text="⚡ 极速批量识别 (纯文字)")
                    self.btn_run_full_batch.configure(state="normal", text="🚀 完整批量处理 (含卡面切片)")
                    total_p = len(self.batch_groups)
                    total_f = len(self.batch_files_map)

                    if with_crop:
                        self.batch_stats_lbl.configure(text=f"共 {total_f} 张图片 · 归属 {total_p} 位人员 · 全部识别与切片完毕")
                        messagebox.showinfo("完成", f"批量识别与图像切片完毕！\n共完成 {len(results)} 位人员。\n请在右侧逐一核对档案与高清切片。")
                    else:
                        self.batch_stats_lbl.configure(text=f"共 {total_f} 张图片 · 归属 {total_p} 位人员 · 全部极速提取完毕")
                        messagebox.showinfo("完成", f"⚡ 批量极速纯文字识别完毕！\n共提取 {len(results)} 位人员文字档案。\n已跳过图像切片，秒级极速完成。")

                    children = self.batch_tree.get_children()
                    if children:
                        self.batch_tree.selection_set(children[0])
                        self._on_batch_tree_selected(None)

                self.after(0, _finish)
            except Exception as e:
                err_msg = str(e)
                def _fail():
                    self.batch_progress_bar.set(0)
                    self.btn_run_fast_batch.configure(state="normal", text="⚡ 极速批量识别 (纯文字)")
                    self.btn_run_full_batch.configure(state="normal", text="🚀 完整批量处理 (含卡面切片)")
                    self.batch_stats_lbl.configure(text=f"共 {len(self.batch_files_map)} 张图片 · 归属 {len(self.batch_groups)} 位人员")
                    messagebox.showerror("错误", f"批量处理异常: {err_msg}")
                self.after(0, _fail)

        threading.Thread(target=_worker, daemon=True).start()


    # ====== 需求 2.b：核心扫描件生成与导出对话框 ======

    def open_batch_scan_dialog(self):
        """弹出 A4 扫描件生成高级配置窗口"""
        if not self._check_auth_or_prompt():
            return
        if not self.batch_results:
            messagebox.showwarning("提示", "当前列表尚未识别，请先导入并处理图片！")
            return

        # 核心改造：彻底取消暗中耗时兜底切片，未切片时直接明确提示引导
        has_any_card = any(
            (r.get("front_image_path", "").lower().endswith(".png") and "front_" in os.path.basename(r.get("front_image_path", "")).lower()) or
            (r.get("back_image_path", "").lower().endswith(".png") and "back_" in os.path.basename(r.get("back_image_path", "")).lower())
            for r in self.batch_results
        )

        if not has_any_card:
            messagebox.showinfo(
                "提示",
                "当前批次为【极速批量识别 (纯文字)】结果，尚未生成卡面切片！\n\n如需导出 A4 扫描件，请直接点击顶栏【🚀 完整批量处理 (含卡面切片)】生成切片后再导出。"
            )
            return


        dialog = ctk.CTkToplevel(self) if USE_CTK else tk.Toplevel(self)
        dialog.title("A4 标准身份证扫描件/复印件生成器")
        dialog.geometry("520x540")
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.attributes("-topmost", True)
        dialog.after(10, dialog.lift)
        dialog.after(20, dialog.focus_force)

        ctk.CTkLabel(dialog, text="🖨️ A4 身份证扫描件导出设置", font=ctk.CTkFont(size=16, weight="bold"), text_color="#f8fafc").pack(pady=(14, 4))

        box = ctk.CTkFrame(dialog, fg_color="#1e293b", corner_radius=10)
        box.pack(fill="x", padx=20, pady=4)

        # 1. 颜色模式选择
        ctk.CTkLabel(box, text="色彩与效果模式:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8").pack(anchor="w", padx=16, pady=(8, 2))
        mode_var = tk.StringVar(value="color")

        r1 = ctk.CTkRadioButton(box, text="🎨 高清彩色扫描件 (提纯去杂质、还原政务高清扫描质感)", variable=mode_var, value="color")
        r1.pack(anchor="w", padx=24, pady=2)

        r2 = ctk.CTkRadioButton(box, text="🖤 黑白复印件 (模拟复印机高保真锐黑与半色调防伪效果)", variable=mode_var, value="bw")
        r2.pack(anchor="w", padx=24, pady=2)

        # 2. 导出范围与格式
        ctk.CTkLabel(box, text="导出格式与组织形式:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8").pack(anchor="w", padx=16, pady=(8, 2))
        export_type = tk.StringVar(value="merge_pdf")

        r3 = ctk.CTkRadioButton(box, text="📑 导出为单个多页 PDF (全员合并，每人一页 A4，适合连续打印)", variable=export_type, value="merge_pdf")
        r3.pack(anchor="w", padx=24, pady=2)

        r4 = ctk.CTkRadioButton(box, text="📄 为每人导出独立 PDF (一人一份，存入 output/scans 目录)", variable=export_type, value="single_pdf")
        r4.pack(anchor="w", padx=24, pady=2)

        r5 = ctk.CTkRadioButton(box, text="🖼️ 为每人导出高清 A4 图片 (一人一份 JPG，分辨率 300DPI)", variable=export_type, value="single_jpg")
        r5.pack(anchor="w", padx=24, pady=2)

        # 3. 防盗防挪用水印
        ctk.CTkLabel(box, text="🛡️ 防盗防挪用倾斜半透明水印 (政务/银行合规规范):", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8").pack(anchor="w", padx=16, pady=(8, 2))

        b_wm_enable = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(box, text="开启防伪防盗用水印 (倾斜覆盖在卡面上，防抠图盗用)", variable=b_wm_enable, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=18, pady=2)

        b_wm_entry = ctk.CTkEntry(box, placeholder_text="请输入水印文字...", height=30, font=ctk.CTkFont(size=12))
        b_wm_entry.insert(0, "仅供办理业务使用 他用无效")
        b_wm_entry.pack(fill="x", padx=16, pady=3)

        b_tag_row = ctk.CTkFrame(box, fg_color="transparent")
        b_tag_row.pack(fill="x", padx=16, pady=(2, 8))
        ctk.CTkLabel(b_tag_row, text="快捷文字:", font=ctk.CTkFont(size=11), text_color="#94a3b8").pack(side="left", padx=(0, 6))

        def set_b_wm(t):
            b_wm_entry.delete(0, "end")
            b_wm_entry.insert(0, t)

        for tag_text, tag_val in [
            ("银行开户", "仅供办理开户业务使用 他用无效"),
            ("入职建档", "仅供入职建档使用 复印无效"),
            ("资质审核", "仅供资质审核备案使用 他用无效")
        ]:
            ctk.CTkButton(
                b_tag_row,
                text=tag_text,
                height=22,
                font=ctk.CTkFont(size=10),
                fg_color="#334155",
                hover_color="#475569",
                command=lambda v=tag_val: set_b_wm(v)
            ).pack(side="left", padx=3)

        def _do_generate():
            mode = mode_var.get()
            etype = export_type.get()
            wm_text = b_wm_entry.get().strip() if b_wm_enable.get() else ""
            dialog.destroy()
            self._execute_generate_scans(mode, etype, wm_text)

        # 执行按钮
        btn_start = ctk.CTkButton(
            dialog, 
            text="🚀 开始批量生成 A4 扫描件", 
            font=ctk.CTkFont(size=13, weight="bold"), 
            fg_color="#8b5cf6", 
            hover_color="#7c3aed", 
            height=36,
            command=_do_generate
        )
        btn_start.pack(fill="x", padx=20, pady=(6, 8))

    def _execute_generate_scans(self, mode: str, etype: str, watermark_text: str = ""):
        """后台多线程执行 A4 扫描件生成 (支持防盗防伪水印叠加)"""
        scans_dir = os.path.join(OUTPUT_DIR, "scans")
        os.makedirs(scans_dir, exist_ok=True)
        self.batch_stats_lbl.configure(text="⏳ 正在生成 A4 扫描件，请稍候...")

        def _worker():
            try:
                pages = []
                single_files = []
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

                def _prepare_batch_card(p, mode_str):
                    if not p or not os.path.exists(p):
                        return None
                    if ("front_" in os.path.basename(p).lower() or "back_" in os.path.basename(p).lower()) and p.lower().endswith((".png", ".jpg")):
                        try:
                            im = Image.open(p)
                            if mode_str == "bw":
                                return convert_card_to_photocopy(im)
                            if im.mode == "RGBA":
                                bg = Image.new("RGB", im.size, (255, 255, 255))
                                bg.paste(im, mask=im.split()[3])
                                return bg
                            return im.convert("RGB")
                        except Exception:
                            pass
                    return correct_and_crop_card(p, mode=mode_str)

                for item in self.batch_results:
                    front_p = item.get("front_image_path")
                    back_p = item.get("back_image_path")
                    name = re.sub(r'[\\/*?:\[\]]', '', str(item.get("name") or item.get("_group_name") or "未命名"))

                    # 生成卡片 (优先复用切片，黑白自适应)
                    card_front = _prepare_batch_card(front_p, mode)
                    card_back = _prepare_batch_card(back_p, mode)

                    # 排版 A4 纸 (带入高对比防盗水印参数)
                    a4_sheet = generate_a4_scanned_page(card_front, card_back, mode=mode, watermark_text=watermark_text)
                    pages.append(a4_sheet)

                    if etype == "single_pdf":
                        pdf_path = os.path.join(scans_dir, f"{name}_A4扫描件_{timestamp}.pdf")
                        export_a4_sheets_to_pdf([a4_sheet], pdf_path)
                        single_files.append(pdf_path)
                    elif etype == "single_jpg":
                        jpg_path = os.path.join(scans_dir, f"{name}_A4扫描件_{timestamp}.jpg")
                        a4_sheet.save(jpg_path, "JPEG", quality=95, dpi=(300, 300))
                        single_files.append(jpg_path)

                if etype == "merge_pdf":
                    merge_pdf_path = os.path.join(scans_dir, f"全员A4扫描件汇总_{timestamp}.pdf")
                    export_a4_sheets_to_pdf(pages, merge_pdf_path)

                    def _succ_merge():
                        self.batch_stats_lbl.configure(text=f"共 {len(self.batch_files_map)} 张图片 · 归属 {len(self.batch_groups)} 位人员")
                        res = messagebox.askyesno("成功", f"全员 A4 扫描件已成功合并导出至：\n{merge_pdf_path}\n（共 {len(pages)} 页 A4，300DPI 印刷级标准）\n\n是否立即打开查看？")
                        if res:
                            os.startfile(merge_pdf_path)
                    self.after(0, _succ_merge)
                else:
                    def _succ_single():
                        self.batch_stats_lbl.configure(text=f"共 {len(self.batch_files_map)} 张图片 · 归属 {len(self.batch_groups)} 位人员")
                        res = messagebox.askyesno("成功", f"已成功为 {len(single_files)} 位人员分别生成专属 A4 扫描件！\n存放目录：\n{scans_dir}\n\n是否立即打开输出文件夹？")
                        if res:
                            os.startfile(scans_dir)
                    self.after(0, _succ_single)

            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda: self.batch_stats_lbl.configure(text=f"共 {len(self.batch_files_map)} 张图片 · 归属 {len(self.batch_groups)} 位人员"))
                self.after(0, lambda: messagebox.showerror("失败", f"生成扫描件异常: {err_msg}"))

        threading.Thread(target=_worker, daemon=True).start()

    # ====== 批量导出与套打 ======

    def export_batch_excel(self):
        if not self._check_auth_or_prompt():
            return
        if not self.batch_results:
            messagebox.showwarning("提示", "暂无批量结果，请先点击【启动批量识别】！")
            return

        out_file = os.path.join(OUTPUT_DIR, f"批量汇总_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
        write_batch_to_excel(self.batch_results, out_file)
        res = messagebox.askyesno("成功", f"批量数据已保存至：\n{out_file}\n\n是否打开查看？")
        if res:
            os.startfile(out_file)

    def fill_batch_merge_template(self):
        if not self._check_auth_or_prompt():
            return
        if not self.batch_results:
            messagebox.showwarning("提示", "暂无批量结果，请先点击【启动批量识别】！")
            return

        tmpl_file = filedialog.askopenfilename(initialdir=USER_TEMPLATES_DIR, title="选择合并套打模板", filetypes=[("模板文件", "*.docx;*.xlsx")])
        if not tmpl_file:
            return

        ext = os.path.splitext(tmpl_file)[1].lower()
        default_out = os.path.join(OUTPUT_DIR, f"邮件合并批量汇总_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}")

        try:
            out_path = merge_fill_template(tmpl_file, self.batch_results, default_out)
            res = messagebox.askyesno("成功", f"邮件合并套打已完成！\n已将全员数据与专属照片合并至单文件：\n{out_path}\n\n是否立即打开查看？")
            if res:
                os.startfile(out_path)
        except Exception as e:
            messagebox.showerror("失败", f"邮件合并套打失败: {e}")

    def fill_batch_templates(self):
        if not self._check_auth_or_prompt():
            return
        if not self.batch_results:
            messagebox.showwarning("提示", "暂无批量结果，请先点击【启动批量识别】！")
            return

        tmpl_file = filedialog.askopenfilename(initialdir=USER_TEMPLATES_DIR, title="选择独立套打模板", filetypes=[("模板文件", "*.docx;*.xlsx")])
        if not tmpl_file:
            return

        try:
            out_files = batch_fill_template(tmpl_file, self.batch_results, OUTPUT_DIR)
            res = messagebox.askyesno("成功", f"已成功批量生成 {len(out_files)} 份独立文件！\n存放于: {OUTPUT_DIR}\n\n是否打开输出目录？")
            if res:
                os.startfile(OUTPUT_DIR)
        except Exception as e:
            messagebox.showerror("失败", f"批量生成失败: {e}")


if __name__ == "__main__":
    app = AppGUI()
    app.mainloop()
