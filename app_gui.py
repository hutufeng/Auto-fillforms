# -*- coding: utf-8 -*-
"""
身份证OCR · 商业标准版 (纯原生轻量 GUI 客户端)
零 HTTP 端口 / 零网络占用 / 毫秒级冷启动 / 15MB~20MB 极小打包
"""

import os
import sys
import threading
from datetime import datetime

# 保证根目录在 sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# 导入业务核心模块 (逻辑 100% 复用)
from auth_manager import auth_manager
from local_ocr import ocr_image, check_ocr_service, get_ocr_engine_name
from id_parser import parse_single_image, parse_id_card, is_front_side, is_back_side
from id_calculator import validate_id
from excel_writer import write_to_excel, write_batch_to_excel
from template_filler import fill_template, batch_fill_template
from batch_processor import group_files, process_batch
from config import UPLOAD_DIR, OUTPUT_DIR, USER_TEMPLATES_DIR

# 界面库优先使用 CustomTkinter，无缝回退至标准 Tkinter
USE_CTK = False
try:
    import customtkinter as ctk
    from PIL import Image, ImageTk
    USE_CTK = True
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
except ImportError:
    import tkinter as ctk
    from tkinter import ttk, messagebox, filedialog
    from PIL import Image, ImageTk

import tkinter as tk
from tkinter import messagebox, filedialog


class AppGUI(ctk.CTk if USE_CTK else tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("身份证OCR · 商业标准版")
        self.geometry("1100 × 740".replace("×", "x"))
        self.minsize(960, 660)

        # 状态变量
        self.front_path = ""
        self.back_path = ""
        self.current_data = {}
        self.batch_files = []
        self.batch_results = []

        self._build_header()
        self._build_tabs()
        self._update_auth_ui()

    def _build_header(self):
        """顶部商业状态栏"""
        if USE_CTK:
            header = ctk.CTkFrame(self, height=60, corner_radius=0, fg_color="#0f172a")
            header.pack(fill="x", side="top", padx=0, pady=0)

            # 左侧品牌标题
            title_box = ctk.CTkFrame(header, fg_color="transparent")
            title_box.pack(side="left", padx=20, pady=10)

            title_lbl = ctk.CTkLabel(
                title_box, 
                text="🪪 身份证OCR", 
                font=ctk.CTkFont(size=18, weight="bold"),
                text_color="#f8fafc"
            )
            title_lbl.pack(side="left")

            badge_lbl = ctk.CTkLabel(
                title_box,
                text="标准核心版",
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color="#1e293b",
                text_color="#38bdf8",
                corner_radius=6,
                padx=8,
                pady=2
            )
            badge_lbl.pack(side="left", padx=10)

            # 右侧状态与操作
            right_box = ctk.CTkFrame(header, fg_color="transparent")
            right_box.pack(side="right", padx=20, pady=10)

            # 机器码胶囊
            hwid_text = f"💻 本机码: {auth_manager.machine_code}"
            self.hwid_btn = ctk.CTkButton(
                right_box,
                text=hwid_text,
                font=ctk.CTkFont(family="Consolas", size=12),
                fg_color="#1e293b",
                hover_color="#334155",
                text_color="#94a3b8",
                height=32,
                command=self.copy_hwid
            )
            self.hwid_btn.pack(side="left", padx=8)

            # 授权状态徽章按钮
            self.auth_badge_btn = ctk.CTkButton(
                right_box,
                text="⚠️ 未激活 (点击激活)",
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="#f59e0b",
                hover_color="#d97706",
                text_color="#ffffff",
                height=32,
                command=self.open_auth_dialog
            )
            self.auth_badge_btn.pack(side="left", padx=8)
        else:
            header = tk.Frame(self, bg="#0f172a", height=50)
            header.pack(fill="x", side="top")
            tk.Label(header, text="🪪 身份证OCR (商业标准版)", font=("微软雅黑", 14, "bold"), fg="#ffffff", bg="#0f172a").pack(side="left", padx=15, pady=10)
            self.auth_badge_btn = tk.Button(header, text="授权激活", bg="#f59e0b", fg="#ffffff", command=self.open_auth_dialog)
            self.auth_badge_btn.pack(side="right", padx=15, pady=10)

    def _build_tabs(self):
        """核心三功能区选项卡"""
        if USE_CTK:
            self.tabview = ctk.CTkTabview(self, corner_radius=12, fg_color="#111827")
            self.tabview.pack(fill="both", expand=True, padx=20, pady=16)

            self.tab_single = self.tabview.add("📷 单图高精度识别")
            self.tab_batch = self.tabview.add("📁 批量分组套打")
            self.tab_template = self.tabview.add("📄 模板智能管理")

            self._build_single_tab(self.tab_single)
            self._build_batch_tab(self.tab_batch)
            self._build_template_tab(self.tab_template)
        else:
            self.tabview = ttk.Notebook(self)
            self.tabview.pack(fill="both", expand=True, padx=10, pady=10)
            self.tab_single = tk.Frame(self.tabview)
            self.tab_batch = tk.Frame(self.tabview)
            self.tabview.add(self.tab_single, text="单图识别")
            self.tabview.add(self.tab_batch, text="批量处理")
            self._build_single_tab(self.tab_single)

    def _build_single_tab(self, parent):
        """单张识别面板布局"""
        # 左侧上传与预览
        left_frame = ctk.CTkFrame(parent, fg_color="#182234", corner_radius=10, width=380)
        left_frame.pack(side="left", fill="both", padx=(0, 10), pady=10)
        left_frame.pack_propagate(False)

        ctk.CTkLabel(left_frame, text="📤 上传身份证原件", font=ctk.CTkFont(size=14, weight="bold"), text_color="#f8fafc").pack(anchor="w", padx=16, pady=(16, 10))

        # 正面插槽
        self.front_btn = ctk.CTkButton(
            left_frame,
            text="🖼️ 点击选择【正面 (人像面)】图片\n(支持单图正反合照自动拆分)",
            font=ctk.CTkFont(size=12),
            height=90,
            fg_color="#0f172a",
            hover_color="#1e293b",
            border_width=1,
            border_color="#334155",
            command=self.select_front_image
        )
        self.front_btn.pack(fill="x", padx=16, pady=8)

        # 反面插槽
        self.back_btn = ctk.CTkButton(
            left_frame,
            text="🖼️ 点击选择【反面 (国徽面)】图片 (可选)",
            font=ctk.CTkFont(size=12),
            height=70,
            fg_color="#0f172a",
            hover_color="#1e293b",
            border_width=1,
            border_color="#334155",
            command=self.select_back_image
        )
        self.back_btn.pack(fill="x", padx=16, pady=8)

        # 清除按钮
        clear_btn = ctk.CTkButton(left_frame, text="重选图片", fg_color="#334155", hover_color="#475569", height=28, command=self.clear_images)
        clear_btn.pack(anchor="e", padx=16, pady=4)

        # 启动识别按钮
        self.btn_run_ocr = ctk.CTkButton(
            left_frame,
            text="🔍 开始高精度提取识别",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            height=44,
            command=self.run_single_ocr
        )
        self.btn_run_ocr.pack(fill="x", padx=16, pady=(20, 10))

        # 右侧结果表单
        right_frame = ctk.CTkFrame(parent, fg_color="#182234", corner_radius=10)
        right_frame.pack(side="right", fill="both", expand=True, padx=(10, 0), pady=10)

        ctk.CTkLabel(right_frame, text="📋 提取结果 (支持就地核对修改)", font=ctk.CTkFont(size=14, weight="bold"), text_color="#f8fafc").pack(anchor="w", padx=20, pady=(16, 12))

        # 表单输入框容器
        form_frame = ctk.CTkScrollableFrame(right_frame, fg_color="transparent")
        form_frame.pack(fill="both", expand=True, padx=16, pady=0)

        self.form_entries = {}
        fields = [
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

        for key, label in fields:
            row = ctk.CTkFrame(form_frame, fg_color="transparent")
            row.pack(fill="x", pady=5)
            lbl = ctk.CTkLabel(row, text=label + ":", width=90, anchor="e", font=ctk.CTkFont(size=13), text_color="#94a3b8")
            lbl.pack(side="left", padx=(0, 10))
            entry = ctk.CTkEntry(row, height=34, font=ctk.CTkFont(size=13), fg_color="#0f172a", border_color="#334155")
            entry.pack(side="left", fill="x", expand=True)
            self.form_entries[key] = entry

        # 警告展示条
        self.warn_lbl = ctk.CTkLabel(right_frame, text="", font=ctk.CTkFont(size=12), text_color="#f59e0b")
        self.warn_lbl.pack(anchor="w", padx=20, pady=4)

        # 底部操作栏
        action_bar = ctk.CTkFrame(right_frame, fg_color="transparent")
        action_bar.pack(fill="x", padx=16, pady=16)

        btn_export = ctk.CTkButton(action_bar, text="📊 导出/追加到 Excel", fg_color="#f59e0b", hover_color="#d97706", height=38, command=self.export_single_excel)
        btn_export.pack(side="left", padx=(0, 10))

        btn_fill = ctk.CTkButton(action_bar, text="📝 套打到 Word/Excel 模板", fg_color="#10b981", hover_color="#059669", height=38, command=self.fill_single_template)
        btn_fill.pack(side="left", padx=10)

    def _build_batch_tab(self, parent):
        """批量处理面板"""
        top_ctrl = ctk.CTkFrame(parent, fg_color="#182234", corner_radius=10)
        top_ctrl.pack(fill="x", padx=10, pady=10)

        btn_select_dir = ctk.CTkButton(top_ctrl, text="📂 选择图片文件夹 / 多张图片", fg_color="#2563eb", height=36, command=self.select_batch_files)
        btn_select_dir.pack(side="left", padx=16, pady=12)

        self.batch_info_lbl = ctk.CTkLabel(top_ctrl, text="未选择图片", text_color="#94a3b8")
        self.batch_info_lbl.pack(side="left", padx=12)

        self.btn_run_batch = ctk.CTkButton(top_ctrl, text="🚀 启动批量识别", fg_color="#10b981", height=36, command=self.run_batch_ocr)
        self.btn_run_batch.pack(side="right", padx=16, pady=12)

        # 结果列表
        self.batch_box = ctk.CTkTextbox(parent, font=ctk.CTkFont(family="Consolas", size=12), fg_color="#0f172a")
        self.batch_box.pack(fill="both", expand=True, padx=10, pady=6)
        self.batch_box.insert("1.0", "选择图片后点击【启动批量识别】，提取清单将在此处展示...\n")

        # 底部导出
        b_bottom = ctk.CTkFrame(parent, fg_color="transparent")
        b_bottom.pack(fill="x", padx=10, pady=10)

        btn_b_excel = ctk.CTkButton(b_bottom, text="📊 批量导出汇总 Excel", fg_color="#f59e0b", height=36, command=self.export_batch_excel)
        btn_b_excel.pack(side="left", padx=6)

        btn_b_fill = ctk.CTkButton(b_bottom, text="📝 一人一份批量套打 Word/Excel", fg_color="#10b981", height=36, command=self.fill_batch_templates)
        btn_b_fill.pack(side="left", padx=12)

    def _build_template_tab(self, parent):
        """模板管理面板"""
        t_frame = ctk.CTkFrame(parent, fg_color="#182234", corner_radius=10)
        t_frame.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(t_frame, text="🏷️ 模板占位符制作指南", font=ctk.CTkFont(size=15, weight="bold"), text_color="#f8fafc").pack(anchor="w", padx=20, pady=(16, 8))
        desc = "在您的 Word (.docx) 或 Excel (.xlsx) 表格/合同中插入以下占位符，生成时会自动替换：\n\n" \
               "{{姓名}}   {{性别}}   {{民族}}   {{出生日期}}   {{年龄}}\n" \
               "{{身份证号码}}   {{住址}}   {{签发机关}}   {{有效期限}}"
        ctk.CTkLabel(t_frame, text=desc, font=ctk.CTkFont(family="Consolas", size=13), justify="left", text_color="#38bdf8").pack(anchor="w", padx=20, pady=6)

        ctk.CTkButton(t_frame, text="📁 打开本地模板存放文件夹 (user_templates)", fg_color="#334155", height=34, command=lambda: os.startfile(USER_TEMPLATES_DIR)).pack(anchor="w", padx=20, pady=14)

    # ====== 业务操作事件 ======

    def copy_hwid(self):
        self.clipboard_clear()
        self.clipboard_append(auth_manager.machine_code)
        messagebox.showinfo("提示", f"本机硬件码已复制到剪贴板！\n{auth_manager.machine_code}\n\n可直接发送给闲鱼卖家兑换专属卡密。")

    def _update_auth_ui(self):
        """刷新授权状态标识"""
        status = auth_manager.get_status()
        if status["is_valid"]:
            exp_text = "永久有效" if status["is_perpetual"] else f"剩余 {status['remaining_days']} 天"
            self.auth_badge_btn.configure(
                text=f"💎 标准核心版 ({exp_text})",
                fg_color="#10b981",
                hover_color="#059669"
            )
        else:
            self.auth_badge_btn.configure(
                text="⚠️ 未激活 (点击输入卡密)",
                fg_color="#f59e0b",
                hover_color="#d97706"
            )

    def open_auth_dialog(self):
        """原生授权激活弹窗"""
        dialog = ctk.CTkToplevel(self) if USE_CTK else tk.Toplevel(self)
        dialog.title("产品授权激活")
        dialog.geometry("460x340")
        dialog.resizable(False, False)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="💎 身份证OCR · 商业授权中心", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(20, 10))

        # 机器码展示与复制
        box = ctk.CTkFrame(dialog, fg_color="transparent")
        box.pack(fill="x", padx=30, pady=5)
        ctk.CTkLabel(box, text="本机硬件码:").pack(anchor="w")
        hwid_entry = ctk.CTkEntry(box, font=ctk.CTkFont(family="Consolas", size=12))
        hwid_entry.insert(0, auth_manager.machine_code)
        hwid_entry.configure(state="readonly")
        hwid_entry.pack(fill="x", pady=4)

        # 卡密输入框
        box2 = ctk.CTkFrame(dialog, fg_color="transparent")
        box2.pack(fill="x", padx=30, pady=10)
        ctk.CTkLabel(box2, text="请输入16位激活卡密 (由闲鱼卖家提供):").pack(anchor="w")
        code_entry = ctk.CTkEntry(box2, font=ctk.CTkFont(family="Consolas", size=13), placeholder_text="例如: ABCD-1234-EFGH-5678")
        code_entry.pack(fill="x", pady=4)

        def do_act():
            code = code_entry.get().strip()
            if not code:
                messagebox.showwarning("提示", "请输入激活卡密！")
                return
            ok, msg = auth_manager.activate_online(code)
            if ok:
                messagebox.showinfo("成功", "🎉 授权激活成功，核心功能已解锁！")
                self._update_auth_ui()
                dialog.destroy()
            else:
                messagebox.showerror("失败", f"激活未通过: {msg}")

        def do_unbind():
            code = code_entry.get().strip()
            if not code:
                messagebox.showwarning("提示", "换机解绑请输入原激活码！")
                return
            ok, msg = auth_manager.unbind_online(code)
            if ok:
                messagebox.showinfo("成功", "已成功解绑此设备！")
                self._update_auth_ui()
                dialog.destroy()
            else:
                messagebox.showerror("失败", f"解绑失败: {msg}")

        btn_act = ctk.CTkButton(dialog, text="⚡ 立即联网验证激活", fg_color="#2563eb", height=38, command=do_act)
        btn_act.pack(fill="x", padx=30, pady=(10, 4))

        btn_unbind = ctk.CTkButton(dialog, text="换机解绑当前授权", fg_color="transparent", text_color="#94a3b8", hover_color="#1e293b", command=do_unbind)
        btn_unbind.pack(pady=4)

    def _check_auth_or_prompt(self) -> bool:
        """鉴权拦截"""
        is_valid, msg, _ = auth_manager.verify_local_license()
        if not is_valid:
            res = messagebox.askyesno("商业版激活提示", f"该功能需要商业授权解锁！\n状态: {msg}\n\n是否立即输入卡密进行激活？")
            if res:
                self.open_auth_dialog()
            return False
        return True

    def select_front_image(self):
        f = filedialog.askopenfilename(title="选择正面图片", filetypes=[("图片", "*.jpg;*.jpeg;*.png;*.bmp")])
        if f:
            self.front_path = f
            self.front_btn.configure(text=f"已选正面:\n{os.path.basename(f)}")

    def select_back_image(self):
        f = filedialog.askopenfilename(title="选择反面图片", filetypes=[("图片", "*.jpg;*.jpeg;*.png;*.bmp")])
        if f:
            self.back_path = f
            self.back_btn.configure(text=f"已选反面:\n{os.path.basename(f)}")

    def clear_images(self):
        self.front_path = ""
        self.back_path = ""
        self.front_btn.configure(text="🖼️ 点击选择【正面 (人像面)】图片\n(支持单图正反合照自动拆分)")
        self.back_btn.configure(text="🖼️ 点击选择【反面 (国徽面)】图片 (可选)")
        for entry in self.form_entries.values():
            entry.delete(0, "end")
        self.warn_lbl.configure(text="")

    def run_single_ocr(self):
        if not self._check_auth_or_prompt():
            return
        if not self.front_path and not self.back_path:
            messagebox.showwarning("提示", "请至少选择一张身份证图片！")
            return

        self.btn_run_ocr.configure(state="disabled", text="正在提取识别中...")

        def _worker():
            try:
                front_lines = ocr_image(self.front_path) if self.front_path else []
                back_lines = ocr_image(self.back_path) if self.back_path else []

                # 单图正反面合图拆分判断
                if self.front_path and not self.back_path and front_lines:
                    data, side = parse_single_image(front_lines)
                else:
                    data = parse_id_card(front_lines, back_lines)

                self.current_data = data

                # UI 填充
                def _update():
                    for k, entry in self.form_entries.items():
                        entry.delete(0, "end")
                        val = data.get(k, "")
                        entry.insert(0, str(val))

                    # 告警
                    warns = data.get("_warnings", [])
                    if warns:
                        self.warn_lbl.configure(text="⚠️ " + "；".join(warns))
                    else:
                        self.warn_lbl.configure(text="")

                    self.btn_run_ocr.configure(state="normal", text="🔍 开始高精度提取识别")
                    messagebox.showinfo("完成", "身份证信息提取完成！")

                self.after(0, _update)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("错误", f"识别异常: {e}"))
                self.after(0, lambda: self.btn_run_ocr.configure(state="normal", text="🔍 开始高精度提取识别"))

        threading.Thread(target=_worker, daemon=True).start()

    def export_single_excel(self):
        if not self._check_auth_or_prompt():
            return
        if not self.form_entries["name"].get():
            messagebox.showwarning("提示", "请先提取或输入身份证数据！")
            return

        # 获取当前表单修改后的数据
        row_data = {k: entry.get().strip() for k, entry in self.form_entries.items()}
        out_file = os.path.join(OUTPUT_DIR, f"身份证台账_{datetime.now().strftime('%Y%m%d')}.xlsx")
        write_to_excel(row_data, out_file)
        res = messagebox.askyesno("成功", f"数据已追加写入 Excel：\n{out_file}\n\n是否立即打开该文件？")
        if res:
            os.startfile(out_file)

    def fill_single_template(self):
        if not self._check_auth_or_prompt():
            return
        tmpl_file = filedialog.askopenfilename(initialdir=USER_TEMPLATES_DIR, title="选择套打模板", filetypes=[("模板文件", "*.docx;*.xlsx")])
        if not tmpl_file:
            return

        row_data = {k: entry.get().strip() for k, entry in self.form_entries.items()}
        name = row_data.get("name") or "未命名"
        ext = os.path.splitext(tmpl_file)[1]
        out_file = os.path.join(OUTPUT_DIR, f"{name}_套打结果{ext}")

        try:
            fill_template(tmpl_file, row_data, out_file)
            res = messagebox.askyesno("成功", f"模板已生成：\n{out_file}\n\n是否立即打开查看？")
            if res:
                os.startfile(out_file)
        except Exception as e:
            messagebox.showerror("失败", f"模板填充失败: {e}")

    # ====== 批量操作 ======

    def select_batch_files(self):
        files = filedialog.askopenfilenames(title="选择多张身份证图片", filetypes=[("图片", "*.jpg;*.jpeg;*.png;*.bmp")])
        if files:
            self.batch_files = list(files)
            self.batch_info_lbl.configure(text=f"已选择 {len(files)} 张图片")

    def run_batch_ocr(self):
        if not self._check_auth_or_prompt():
            return
        if not self.batch_files:
            messagebox.showwarning("提示", "请先选择需要批量识别的图片！")
            return

        # 临时将所选文件复制到临时目录进行分组识别
        batch_temp = os.path.join(UPLOAD_DIR, f"gui_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        os.makedirs(batch_temp, exist_ok=True)
        import shutil
        for f in self.batch_files:
            shutil.copy2(f, batch_temp)

        self.btn_run_batch.configure(state="disabled", text="正在高速批量识别...")

        def _worker():
            try:
                results = process_batch(batch_temp)
                self.batch_results = results

                def _show():
                    self.batch_box.delete("1.0", "end")
                    for r in results:
                        line = f"姓名: {r.get('name','-')} | 性别: {r.get('gender','-')} | 号码: {r.get('id_number','-')} | 住址: {r.get('address','-')}\n"
                        self.batch_box.insert("end", line)
                    self.btn_run_batch.configure(state="normal", text="🚀 启动批量识别")
                    messagebox.showinfo("完成", f"批量识别完毕！共成功处理 {len(results)} 位人员。")

                self.after(0, _show)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("错误", f"批量处理异常: {e}"))
                self.after(0, lambda: self.btn_run_batch.configure(state="normal", text="🚀 启动批量识别"))

        threading.Thread(target=_worker, daemon=True).start()

    def export_batch_excel(self):
        if not self._check_auth_or_prompt():
            return
        if not self.batch_results:
            messagebox.showwarning("提示", "暂无批量识别结果！")
            return

        out_file = os.path.join(OUTPUT_DIR, f"批量汇总_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
        write_batch_to_excel(self.batch_results, out_file)
        res = messagebox.askyesno("成功", f"批量数据已保存至：\n{out_file}\n\n是否打开查看？")
        if res:
            os.startfile(out_file)

    def fill_batch_templates(self):
        if not self._check_auth_or_prompt():
            return
        if not self.batch_results:
            messagebox.showwarning("提示", "暂无批量识别结果！")
            return

        tmpl_file = filedialog.askopenfilename(initialdir=USER_TEMPLATES_DIR, title="选择批量套打模板", filetypes=[("模板文件", "*.docx;*.xlsx")])
        if not tmpl_file:
            return

        try:
            out_files = batch_fill_template(tmpl_file, self.batch_results, OUTPUT_DIR)
            res = messagebox.askyesno("成功", f"已成功批量生成 {len(out_files)} 份独立文件！\n保存在: {OUTPUT_DIR}\n\n是否打开输出目录？")
            if res:
                os.startfile(OUTPUT_DIR)
        except Exception as e:
            messagebox.showerror("失败", f"批量生成失败: {e}")


if __name__ == "__main__":
    app = AppGUI()
    app.mainloop()
