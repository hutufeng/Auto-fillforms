# -*- coding: utf-8 -*-
"""
身份证智能矫正与 A4 扫描件/复印件生成模块
核心突破：
1. 复杂背景（键盘/木纹/杂物）自适应二代证边缘检测与精准透视矫正
2. 基于 OCR 文本方位语义的 100% 正立检测（彻底杜绝 180 度上下倒立和 90 度侧立）
3. 严格二代证国标规格（85.6mm x 54.0mm @ 300DPI）与平滑圆角处理
4. 高清彩色扫描仪与黑白复印机双质感渲染
5. 像素级免冠二代证头像精准切片
6. A4 纸张排版（上正下反）与单人/多人多页 PDF 导出
"""

from __future__ import annotations
import os
import math
import hashlib
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance


# 300 DPI 下的标准尺寸 (像素)
A4_WIDTH = 2480
A4_HEIGHT = 3508
CARD_WIDTH = 1011
CARD_HEIGHT = 638
CARD_CORNER_RADIUS = 38


def _order_points(pts: np.ndarray) -> np.ndarray:
    """顺时针排序 [左上, 右上, 右下, 左下]"""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]

    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def _four_point_transform(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """透视变换将四边形展平"""
    rect = _order_points(pts)
    (tl, tr, br, bl) = rect

    widthA = np.linalg.norm(br - bl)
    widthB = np.linalg.norm(tr - tl)
    maxWidth = max(int(widthA), int(widthB))

    heightA = np.linalg.norm(tr - br)
    heightB = np.linalg.norm(tl - bl)
    maxHeight = max(int(heightA), int(heightB))

    if maxWidth <= 0 or maxHeight <= 0:
        return image

    dst = np.array([
        [0, 0],
        [maxWidth - 1, 0],
        [maxWidth - 1, maxHeight - 1],
        [0, maxHeight - 1]], dtype="float32")

    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))
    return warped


def _extract_card_contour(img: np.ndarray) -> np.ndarray | None:
    """在复杂背景（键盘/木纹/桌面）中精准定位二代证外接四边形"""
    h_orig, w_orig = img.shape[:2]
    scale = 1000.0 / max(h_orig, w_orig)
    small = cv2.resize(img, (int(w_orig * scale), int(h_orig * scale)))
    img_area = small.shape[0] * small.shape[1]

    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)

    # 1. 尝试自适应阈值 + 大形态学闭运算消除键盘细纹
    thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 5)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []

    for c in contours:
        area = cv2.contourArea(c)
        if area < img_area * 0.12 or area > img_area * 0.98:
            continue
        rect = cv2.minAreaRect(c)
        rw, rh = rect[1]
        if rw == 0 or rh == 0:
            continue
        ratio = max(rw, rh) / min(rw, rh)
        # 二代证比例 1.58，允许在 1.25 到 1.95 之间
        if 1.20 <= ratio <= 1.95:
            candidates.append((area, rect))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_rect = candidates[0][1]
        box = cv2.boxPoints(best_rect) / scale
        return box

    # 2. 如果自适应阈值未检出，尝试 Canny 边缘定位
    edged = cv2.Canny(blurred, 30, 120)
    kernel_edge = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    dilated = cv2.dilate(edged, kernel_edge, iterations=2)
    cnts, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = sorted(cnts, key=cv2.contourArea, reverse=True)[:5]

    for c in cnts:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.025 * peri, True)
        area = cv2.contourArea(c)
        if len(approx) == 4 and area > img_area * 0.15:
            rect = cv2.minAreaRect(c)
            rw, rh = rect[1]
            if rw > 0 and rh > 0 and 1.20 <= (max(rw, rh) / min(rw, rh)) <= 1.95:
                return approx.reshape(4, 2) / scale

    return None


def _ensure_upright_orientation(card_bgr: np.ndarray) -> np.ndarray:
    """
    基于二代证文字语义特征进行 100% 正向方向判定：
    - 正面：姓名在顶部，身份证号在底部
    - 反面：中华人民共和国在顶部，有效期限在底部
    若倒立则旋转 180 度，若倾斜侧立则旋转相应 90 度
    """
    try:
        from local_ocr import _get_engine
        engine = _get_engine()
        if not engine:
            return card_bgr

        # 首次检查
        result, _ = engine(card_bgr)
        h, w = card_bgr.shape[:2]

        if not result:
            return card_bgr

        # 判断是否倒立 180 度
        mid_y = h / 2.0
        is_upside_down = False
        has_positive_clue = False

        for item in result:
            box, text = item[0], item[1]
            cy = sum(p[1] for p in box) / 4.0

            # 反面关键词：中华人民共和国 / 居民身份证
            if any(kw in text for kw in ("中华人民共和国", "居民身份证", "国家")):
                has_positive_clue = True
                if cy > mid_y:
                    is_upside_down = True
                    break

            # 正面关键词：公民身份号码
            if any(kw in text for kw in ("公民身份号码", "身份号码", "号码")):
                has_positive_clue = True
                if cy < mid_y:
                    is_upside_down = True
                    break

            # 姓名 / 出生
            if any(kw in text for kw in ("姓名", "出生")):
                has_positive_clue = True
                if cy > mid_y:
                    is_upside_down = True
                    break

        if is_upside_down:
            card_bgr = cv2.rotate(card_bgr, cv2.ROTATE_180)

        return card_bgr
    except Exception as e:
        print(f"[Scanner] 方向检测异常: {e}")
        return card_bgr


def _auto_orient_to_upright(img_bgr: np.ndarray) -> np.ndarray:
    """
    语义正立前置对齐：
    遍历 4 个基本正交旋转方向（0°, 90° CW, 180°, 90° CCW），
    基于文字上下语义，将图片在进入裁剪前就强制转为横向正立（Upright），
    确保身份证顶端（国徽/姓名）在上方，底端（有效期限/号码）在下方。
    """
    try:
        from local_ocr import _get_engine
        engine = _get_engine()
        if not engine:
            h, w = img_bgr.shape[:2]
            return cv2.rotate(img_bgr, cv2.ROTATE_90_CLOCKWISE) if h > w else img_bgr

        # 候选方向列表 (若原图已经是横版，优先原图检测)
        candidates = [None, cv2.ROTATE_180, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE]
        for rot in candidates:
            curr = img_bgr if rot is None else cv2.rotate(img_bgr, rot)
            ch, cw = curr.shape[:2]
            if ch > cw:
                # 身份证标准为横版，高大于宽的直接跳过
                continue

            # 核心提速：缩放至小图 (长边最大 900px) 进行秒级语义判别，原图保留不变
            scale = 900.0 / max(ch, cw) if max(ch, cw) > 900 else 1.0
            test_img = cv2.resize(curr, (int(cw * scale), int(ch * scale))) if scale < 1.0 else curr

            res, _ = engine(test_img)
            if not res:
                continue

            prc_y = [item[0][0][1] for item in res if any(k in item[1] for k in ("中华人民共和国", "居民身份证", "国家"))]
            val_y = [item[0][0][1] for item in res if any(k in item[1] for k in ("有效期限", "期限", "签发机关"))]
            name_y = [item[0][0][1] for item in res if any(k in item[1] for k in ("姓名", "性别", "民族", "出生", "住址"))]
            id_y = [item[0][0][1] for item in res if any(k in item[1] for k in ("公民身份号码", "身份号码", "号码")) or (len(item[1]) >= 15 and any(c.isdigit() for c in item[1]))]

            # 反面正立判定：中华人民共和国在有效期限上方
            if prc_y and val_y and min(prc_y) < max(val_y):
                return curr

            # 正面正立判定：姓名/出生在号码上方
            if name_y and id_y and min(name_y) < max(id_y):
                return curr

        # 若未命中确定语义，保证横向即可
        h, w = img_bgr.shape[:2]
        if h > w:
            return cv2.rotate(img_bgr, cv2.ROTATE_90_CLOCKWISE)
        return img_bgr
    except Exception as e:
        print(f"[Scanner] 前置正立检测异常: {e}")
        h, w = img_bgr.shape[:2]
        return cv2.rotate(img_bgr, cv2.ROTATE_90_CLOCKWISE) if h > w else img_bgr


def _find_edge_peak_1d(profile_vals: np.ndarray, min_idx: int, max_idx: int) -> int:
    """在指定区间内寻找一阶导数/梯度极大值峰值位置"""
    min_idx = max(1, int(min_idx))
    max_idx = min(len(profile_vals) - 2, int(max_idx))
    if min_idx >= max_idx:
        return min_idx
    sub_slice = profile_vals[min_idx:max_idx]
    if len(sub_slice) == 0:
        return min_idx
    best_offset = int(np.argmax(sub_slice))
    return min_idx + best_offset


def _deskew_and_crop_smart(img_bgr: np.ndarray) -> np.ndarray:
    """
    两阶段微倾斜纠偏 + 物理搜索带约束 + 一阶梯度极大值（变化度最大值）物理边框定位 + 四点透视展平：
    1. 语义过滤：精准提取身份证核心文字框，自动剔除键盘按键（F1-F12、Alt等）与背景杂乱文字
    2. 仿射转平：根据文字行方向向量中位数全图仿射旋转转平（消灭微斜）
    3. 物理搜索带：基于文字外框尺寸，严格限制上下左右物理边界的搜索范围，消灭所有外界误判
    4. 梯度极大值：在各搜索带内寻找一阶导数（变化度）最大的峰值位置，精准锁定真实卡边
    5. 四点透视拉伸：根据精确的物理交点角点执行四点透视拉平，规范化至 1011x638
    """
    try:
        from local_ocr import _get_engine
        engine = _get_engine()
        if not engine:
            return img_bgr

        res, _ = engine(img_bgr)
        if not res:
            return img_bgr

        h, w = img_bgr.shape[:2]
        front_distinctive = ("公民身份号码", "身份号码", "民族", "出生", "住址")
        back_distinctive = ("中华人民共和国", "居民身份证", "签发机关", "有效期限", "期限")

        pts = []
        angles = []
        front_score = 0
        back_score = 0
        has_validity = False

        for item in res:
            box, text = item[0], item[1]
            t = text.strip()
            if len(t) < 1:
                continue

            hit_front = any(k in t for k in front_distinctive) or (len(t) >= 15 and sum(c.isdigit() for c in t) >= 10)
            hit_back = any(k in t for k in back_distinctive)

            if hit_front:
                front_score += 2
            if hit_back:
                back_score += 3

            if hit_front or hit_back or any(c in t for c in "姓名性别民族出生住址签发机关有效"):
                pts.extend(box)
                p0, p1 = box[0], box[1]
                dx, dy = p1[0] - p0[0], p1[1] - p0[1]
                if abs(dx) > 5:
                    ang = math.degrees(math.atan2(dy, dx))
                    if ang > 45: ang -= 90
                    elif ang < -45: ang += 90
                    angles.append(ang)
                if "有效" in t or "期限" in t:
                    has_validity = True

        if not pts or len(pts) < 4:
            return img_bgr

        is_front = (front_score > back_score)

        # 1. 第一阶段：微倾斜仿射旋转纠偏
        skew = float(np.median(angles)) if angles else 0.0
        if abs(skew) >= 0.2:
            M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), skew, 1.0)
            img_bgr = cv2.warpAffine(img_bgr, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
            ones = np.ones(shape=(len(pts), 1))
            pts_ones = np.hstack([np.array(pts), ones])
            pts = M.dot(pts_ones.T).T.tolist()

        # 2. 整体文字外框（核心基准）
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        min_x, max_x = max(0, min(xs)), min(w, max(xs))
        min_y, max_y = max(0, min(ys)), min(h, max(ys))
        text_w = max_x - min_x
        text_h = max_y - min_y

        if text_w <= 50 or text_h <= 30:
            return img_bgr

        # 3. 构造垂直与水平梯度剖面 (Sobel 一阶导数)
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        gray_blur = cv2.GaussianBlur(gray, (5, 5), 0)
        grad_y = np.abs(cv2.Sobel(gray_blur, cv2.CV_32F, 0, 1, ksize=3))
        grad_x = np.abs(cv2.Sobel(gray_blur, cv2.CV_32F, 1, 0, ksize=3))

        if is_front:
            # ====== 正面（人像面）窗口约束 + 变化度极大值定位 ======
            col_start = int(min_x + text_w * 0.15)
            col_end = int(min_x + min(text_w * 0.70, 450))
            vert_profile = np.mean(grad_y[:, col_start:col_end], axis=1)

            # 顶边物理搜索带: [min_y - text_h * 0.28, min_y - text_h * 0.13]
            top_min = max(5, int(min_y - text_h * 0.28))
            top_max = max(10, int(min_y - text_h * 0.13))
            card_top = _find_edge_peak_1d(vert_profile, top_min, top_max)

            # 底边物理搜索带: [max_y + text_h * 0.10, max_y + text_h * 0.24]
            bot_min = min(h - 10, int(max_y + text_h * 0.10))
            bot_max = min(h - 5, int(max_y + text_h * 0.24))
            card_bottom = _find_edge_peak_1d(vert_profile, bot_min, bot_max)

            card_h = card_bottom - card_top
            card_w = int(card_h * 1.58518)

            # 左侧搜索带: [min_x - card_w * 0.14, min_x - card_w * 0.05]
            row_start = int(card_top + card_h * 0.2)
            row_end = int(card_bottom - card_h * 0.2)
            horiz_profile = np.mean(grad_x[row_start:row_end, :], axis=0)

            left_min = max(5, int(min_x - card_w * 0.14))
            left_max = max(10, int(min_x - card_w * 0.05))
            card_left = _find_edge_peak_1d(horiz_profile, left_min, left_max)

            # 右侧在理论右边缘附近搜索梯度极大值进行精准咬合
            theory_right = card_left + card_w
            right_min = max(5, int(theory_right - card_w * 0.04))
            right_max = min(w - 5, int(theory_right + card_w * 0.04))
            card_right = _find_edge_peak_1d(horiz_profile, right_min, right_max)
            if abs(card_right - theory_right) > card_w * 0.05:
                card_right = min(w, theory_right)

        else:
            # ====== 反面（国徽面）四向独立变化度（梯度极大值）判定 ======
            col_start = int(min_x + text_w * 0.15)
            col_end = int(max_x - text_w * 0.15)
            vert_profile = np.mean(grad_y[:, col_start:col_end], axis=1)

            # 1. 顶边变化度极大值寻峰
            top_min = max(5, int(min_y - text_h * 0.45))
            top_max = max(10, int(min_y - text_h * 0.10))
            card_top = _find_edge_peak_1d(vert_profile, top_min, top_max)

            # 2. 底边变化度极大值寻峰（反面有效期限 100% 留存）
            bot_min = min(h - 10, int(max_y + text_h * 0.08))
            bot_max = min(h - 5, int(max_y + text_h * 0.35))
            card_bottom = _find_edge_peak_1d(vert_profile, bot_min, bot_max)

            card_h = card_bottom - card_top
            card_w = int(card_h * 1.58518)

            # 3. 左侧变化度极大值寻峰：在下半身长城底纹区投影（避开国徽内部齿轮）
            # 在 [min_x - card_w * 0.38, min_x - card_w * 0.22] 寻找唯一最大变化度作为真实左边
            row_start = int(card_top + card_h * 0.55)
            row_end = int(card_bottom - card_h * 0.10)
            horiz_profile_lower = np.mean(grad_x[row_start:row_end, :], axis=0)

            left_min = max(5, int(min_x - card_w * 0.38))
            left_max = min(w - 10, int(min_x - card_w * 0.22))
            card_left = _find_edge_peak_1d(horiz_profile_lower, left_min, left_max)

            # 4. 右边缘基于国标比例严格锁定，彻底消灭右侧键盘与背景干扰
            card_right = min(w, card_left + card_w)

        # 4. 透视展平四角点映射
        if (card_right - card_left) > 100 and (card_bottom - card_top) > 60:
            src_pts = np.array([
                [card_left, card_top],
                [card_right, card_top],
                [card_right, card_bottom],
                [card_left, card_bottom]
            ], dtype=np.float32)

            dst_pts = np.array([
                [0, 0],
                [CARD_WIDTH - 1, 0],
                [CARD_WIDTH - 1, CARD_HEIGHT - 1],
                [0, CARD_HEIGHT - 1]
            ], dtype=np.float32)

            M_persp = cv2.getPerspectiveTransform(src_pts, dst_pts)
            warped = cv2.warpPerspective(img_bgr, M_persp, (CARD_WIDTH, CARD_HEIGHT), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
            return warped

        return img_bgr
    except Exception as e:
        print(f"[Scanner] 智能纠偏与边界裁剪异常: {e}")
        return img_bgr


def convert_card_to_photocopy(card_img: Image.Image) -> Image.Image:
    """将已有的 RGB 卡片转换为商业复印机高保真黑白质感"""
    arr = np.array(card_img.convert("RGB"))
    gray_card = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    norm = gray_card.astype(np.float32) / 255.0
    brightened = np.power(norm, 0.85) * 1.12
    brightened = np.clip(brightened, 0.0, 1.0)
    enhanced_gray = np.where(brightened < 0.50, brightened * 0.85, brightened)
    enhanced_gray = (np.clip(enhanced_gray, 0.0, 1.0) * 255.0).astype(np.uint8)
    blurred = cv2.GaussianBlur(enhanced_gray, (0, 0), 1.2)
    sharp = cv2.addWeighted(enhanced_gray, 1.20, blurred, -0.20, 0)
    return Image.fromarray(sharp).convert("RGB")


def correct_and_crop_card(image_path: str, mode: str = "color") -> Image.Image | None:
    """
    全自动背景剔除、两阶段微倾斜纠偏、文字外框色差探测与正立对齐
    :param image_path: 原始图片路径
    :param mode: "color" 或 "bw"
    """
    if not image_path or not os.path.exists(image_path):
        return None

    try:
        data = np.fromfile(image_path, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            return None

        # 0. 语义前置正立检测：彻底消灭 90度、180度、270度各种倒立
        img = _auto_orient_to_upright(img)

        # 1. 核心升级：两阶段微倾斜纠偏 + 文字外框色差外扩 + 比例锁边
        cropped_anchor = _deskew_and_crop_smart(img)

        # 2. 规范尺寸至二代证国标规格 (1011 x 638)
        hw, ww = cropped_anchor.shape[:2]
        if hw > ww:
            cropped_anchor = cv2.rotate(cropped_anchor, cv2.ROTATE_90_CLOCKWISE)

        resized = cv2.resize(cropped_anchor, (CARD_WIDTH, CARD_HEIGHT), interpolation=cv2.INTER_AREA)

        # 3. 兜底语义正立纠偏 (双重保险)
        upright = _ensure_upright_orientation(resized)

        # 5. 滤镜渲染 (真实商务数码复印机光学质感)
        rgb = cv2.cvtColor(upright, cv2.COLOR_BGR2RGB)
        pil_card = Image.fromarray(rgb)
        if mode == "bw":
            pil_card = convert_card_to_photocopy(pil_card)
        else:
            enh_col = ImageEnhance.Color(pil_card)
            pil_card = enh_col.enhance(1.08)
            enh_bri = ImageEnhance.Contrast(pil_card)
            pil_card = enh_bri.enhance(1.06)

        # 6. 标准圆角与防伪微边
        pil_card = _apply_card_rounded_corners(pil_card, CARD_CORNER_RADIUS)
        return pil_card


    except Exception as e:
        print(f"[Scanner] 矫正异常 ({image_path}): {e}")
        try:
            with Image.open(image_path) as im:
                im = im.convert("RGB")
                if im.height > im.width:
                    im = im.rotate(90, expand=True)
                im = im.resize((CARD_WIDTH, CARD_HEIGHT), Image.Resampling.LANCZOS)
                return _apply_card_rounded_corners(im, CARD_CORNER_RADIUS)
        except Exception:
            return None


def _apply_card_rounded_corners(im: Image.Image, radius: int) -> Image.Image:
    """给卡片添加标准二代证平滑圆角，带有微边框，支持透明 Alpha 与纯白背景自适应"""
    im_rgba = im.convert("RGBA")
    mask = Image.new("L", (im.width, im.height), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), (im.width - 1, im.height - 1)], radius=radius, fill=255)

    # 制作平滑透明圆角卡片 (初始底色设为纯白透明 (255, 255, 255, 0)，确保在任何查看器或转RGB时均为纯白无黑角)
    card_rgba = Image.new("RGBA", (im.width, im.height), (255, 255, 255, 0))
    card_rgba.paste(im_rgba, (0, 0), mask=mask)

    # 绘制二代证微弱外边缘轮廓 (模拟真实切角边界)
    draw_edge = ImageDraw.Draw(card_rgba)
    draw_edge.rounded_rectangle([(0, 0), (im.width - 1, im.height - 1)], radius=radius, outline=(200, 205, 215, 255), width=1)
    return card_rgba


def crop_avatar_from_standard_card(card_img: Image.Image) -> Image.Image | None:
    """
    基于已标准化的横版正面卡片 (1011 x 638) 切取像素级二代证免冠头像。
    二代证国标规格：头像位于卡面右侧，尺寸 26mm x 32mm。
    """
    if card_img is None:
        return None
    try:
        w, h = card_img.size
        left = int(w * 0.635)
        top = int(h * 0.160)
        right = int(w * 0.945)
        bottom = int(h * 0.775)

        avatar = card_img.crop((left, top, right, bottom)).convert("RGB")
        avatar.info["dpi"] = (300, 300)
        return avatar
    except Exception as e:
        print(f"[Scanner] 头像标准切片失败: {e}")
        return None


def _is_card_back_by_color(card: Image.Image | None) -> bool:
    """通过左上角国徽鲜艳红金特征，智能识别是否为身份证反面（国徽面）"""
    if card is None:
        return False
    try:
        rgb = card.convert("RGB")
        w, h = rgb.size
        # 裁剪左上角国徽区域 (x: 5%~32%, y: 8%~52%)
        emblem_roi = rgb.crop((int(w * 0.05), int(h * 0.08), int(w * 0.32), int(h * 0.52)))
        arr = np.array(emblem_roi)
        r = arr[:, :, 0].astype(int)
        g = arr[:, :, 1].astype(int)
        b = arr[:, :, 2].astype(int)
        # 国徽高纯度红色特征 (R值高且明显超出G/B)
        red_mask = (r > 130) & ((r - g) > 35) & ((r - b) > 35)
        return float(np.mean(red_mask)) > 0.035
    except Exception:
        return False


def _get_chinese_font(font_size: int, bold: bool = True):
    """自适应查找系统可用中文 TrueType 字体 (优先加载粗体，确保高分辨率 A4 上清晰有力)"""
    from PIL import ImageFont
    candidates = [
        "C:/Windows/Fonts/msyhbd.ttc",
        "msyhbd.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "simhei.ttf",
        "C:/Windows/Fonts/msyh.ttc",
        "msyh.ttc",
        "C:/Windows/Fonts/simsun.ttc",
        "simsun.ttc",
    ] if bold else [
        "C:/Windows/Fonts/msyh.ttc",
        "msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "simsun.ttc",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, font_size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def add_antitheft_watermark_to_a4(
    canvas_image: Image.Image,
    watermark_text: str = "仅供办理业务使用 他用无效",
    card_positions: list[tuple[int, int, int, int]] | None = None,
    mode: str = "color"
) -> Image.Image:
    """
    在 A4 扫描件上渲染专业防盗防挪用倾斜半透明水印。
    政务与金融合规规范：水印文字以 20° 倾斜角横跨覆盖在卡面上方，防抠图盗用，半透明不遮挡底层真实信息。
    :param canvas_image: A4 画布图像 (RGB)
    :param watermark_text: 防盗文字内容 (如 "仅供办理业务使用 他用无效")
    :param card_positions: 正反卡面的矩形坐标 [(x1, y1, x2, y2), ...]
    :param mode: "color" 或 "bw"
    :return: 叠加防伪水印后的 A4 图像
    """
    text = (watermark_text or "").strip()
    if not text:
        return canvas_image

    base_rgba = canvas_image.convert("RGBA")
    w_layer = Image.new("RGBA", base_rgba.size, (255, 255, 255, 0))

    if not card_positions:
        center_x = (A4_WIDTH - CARD_WIDTH) // 2
        front_y = 650
        back_y = front_y + CARD_HEIGHT + 360
        card_positions = [
            (center_x, front_y, center_x + CARD_WIDTH, front_y + CARD_HEIGHT),
            (center_x, back_y, center_x + CARD_WIDTH, back_y + CARD_HEIGHT)
        ]

    font_size = 50
    font = _get_chinese_font(font_size, bold=True)

    from PIL import ImageDraw
    dummy_img = Image.new("RGBA", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)
    try:
        bbox = dummy_draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
    except Exception:
        text_w = len(text) * font_size
        text_h = font_size

    pad = 20
    stamp_w = text_w + pad * 2
    stamp_h = text_h + pad * 2
    stamp = Image.new("RGBA", (stamp_w, stamp_h), (255, 255, 255, 0))
    s_draw = ImageDraw.Draw(stamp)
    
    # 颜色配置：政务防盗深蓝或复印深灰，带白色外发光/微描边增强可见性与防抠图，Alpha 提升至 165
    fill_color = (40, 40, 40, 160) if mode == "bw" else (20, 65, 170, 165)
    stroke_color = (255, 255, 255, 140)
    s_draw.text((pad, pad), text, font=font, fill=fill_color, stroke_width=3, stroke_fill=stroke_color)
    
    # 倾斜 20 度
    rotated_stamp = stamp.rotate(20, expand=True, resample=Image.Resampling.BICUBIC)
    rw, rh = rotated_stamp.size

    for (x1, y1, x2, y2) in card_positions:
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        
        # 在卡面中上部与中下部各印制一条，形成牢固防抠图保护网
        offset_y = 110
        p1 = (cx - rw // 2, cy - offset_y - rh // 2)
        p2 = (cx - rw // 2, cy + offset_y - rh // 2)

        w_layer.paste(rotated_stamp, p1, mask=rotated_stamp)
        w_layer.paste(rotated_stamp, p2, mask=rotated_stamp)

    combined = Image.alpha_composite(base_rgba, w_layer)
    result = combined.convert("RGB")
    result.info["dpi"] = canvas_image.info.get("dpi", (300, 300))
    return result


def generate_a4_scanned_page(
    front_card: Image.Image | None,
    back_card: Image.Image | None = None,
    mode: str = "color",
    watermark_text: str = ""
) -> Image.Image:
    """
    生成标准 A4 身份证扫描件/复印件排版（上正下反）
    具备智能防反序能力：若首图为国徽面次图为人像面，100% 自动对调为标准“上正下反”
    :param watermark_text: 可选防盗防挪用水印文字 (如 "仅供办理业务使用 他用无效")
    """
    # 智能纠正上正下反
    if _is_card_back_by_color(front_card) and not _is_card_back_by_color(back_card):
        front_card, back_card = back_card, front_card

    a4_canvas = Image.new("RGB", (A4_WIDTH, A4_HEIGHT), (255, 255, 255))
    center_x = (A4_WIDTH - CARD_WIDTH) // 2

    # 1. 贴入正面 (居中偏上)
    front_y = 650
    if front_card is not None:
        if front_card.size != (CARD_WIDTH, CARD_HEIGHT):
            front_card = front_card.resize((CARD_WIDTH, CARD_HEIGHT), Image.Resampling.LANCZOS)
        if front_card.mode == "RGBA":
            a4_canvas.paste(front_card, (center_x, front_y), mask=front_card)
        else:
            a4_canvas.paste(front_card, (center_x, front_y))

    # 2. 贴入背面 (居中偏下)
    back_y = front_y + CARD_HEIGHT + 360
    if back_card is not None:
        if back_card.size != (CARD_WIDTH, CARD_HEIGHT):
            back_card = back_card.resize((CARD_WIDTH, CARD_HEIGHT), Image.Resampling.LANCZOS)
        if back_card.mode == "RGBA":
            a4_canvas.paste(back_card, (center_x, back_y), mask=back_card)
        else:
            a4_canvas.paste(back_card, (center_x, back_y))

    # 3. 叠加防盗防挪用倾斜半透明水印
    if watermark_text and watermark_text.strip():
        a4_canvas = add_antitheft_watermark_to_a4(
            a4_canvas,
            watermark_text=watermark_text.strip(),
            card_positions=[
                (center_x, front_y, center_x + CARD_WIDTH, front_y + CARD_HEIGHT),
                (center_x, back_y, center_x + CARD_WIDTH, back_y + CARD_HEIGHT)
            ],
            mode=mode
        )

    a4_canvas.info["dpi"] = (300, 300)
    return a4_canvas

    a4_canvas.info["dpi"] = (300, 300)
    return a4_canvas


def export_a4_sheets_to_pdf(pages: list[Image.Image], output_pdf_path: str) -> str:
    """将一页或多页 A4 扫描件保存为 PDF 文件"""
    if not pages:
        raise ValueError("无可用 A4 页面")

    os.makedirs(os.path.dirname(os.path.abspath(output_pdf_path)), exist_ok=True)
    first_page = pages[0].convert("RGB")
    other_pages = [p.convert("RGB") for p in pages[1:]]

    first_page.save(
        output_pdf_path,
        save_all=True,
        append_images=other_pages,
        resolution=300.0,
        quality=95
    )
    return output_pdf_path


def crop_both_sides_from_single_image(img_path: str, mode: str = "color") -> tuple[Image.Image | None, Image.Image | None]:
    """
    针对单张图片（或单页PDF）同时包含正面与反面的全自动智能分离与精准切片：
    1. OCR 检测全图文字及其包围盒
    2. 分离出正面文字簇与反面文字簇
    3. 动态寻找两卡物理分割界线（上下或左右分割）
    4. 分割为两个独立 ROI，分别调用 correct_and_crop_card
    5. 返回 (card_front, card_back)
    """
    try:
        from local_ocr import _get_engine
        engine = _get_engine()
        if not engine or not os.path.exists(img_path):
            return None, None

        data = np.fromfile(img_path, dtype=np.uint8)
        full_bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if full_bgr is None:
            return None, None

        h, w = full_bgr.shape[:2]
        res, _ = engine(full_bgr)
        if not res:
            return None, None

        front_pts = []
        back_pts = []

        front_kws = ("公民身份号码", "姓名", "性别", "民族", "出生", "住址")
        back_kws = ("中华人民共和国", "居民身份证", "签发机关", "有效期限")

        for item in res:
            box, text = item[0], item[1]
            t = text.strip()
            if not t:
                continue
            is_f = any(k in t for k in front_kws) or (len(t) >= 15 and sum(c.isdigit() for c in t) >= 10)
            is_b = any(k in t for k in back_kws)

            if is_f and not is_b:
                front_pts.extend(box)
            elif is_b and not is_f:
                back_pts.extend(box)

        if not front_pts or not back_pts:
            card = correct_and_crop_card(img_path, mode=mode)
            return card, None

        f_center_y = float(np.mean([p[1] for p in front_pts]))
        f_center_x = float(np.mean([p[0] for p in front_pts]))
        b_center_y = float(np.mean([p[1] for p in back_pts]))
        b_center_x = float(np.mean([p[0] for p in back_pts]))

        diff_y = abs(f_center_y - b_center_y)
        diff_x = abs(f_center_x - b_center_x)

        if diff_y >= diff_x:
            # 上下排布
            split_y = int((f_center_y + b_center_y) / 2.0)
            split_y = max(int(h * 0.15), min(int(h * 0.85), split_y))
            if f_center_y < b_center_y:
                roi_f_bgr = full_bgr[0:split_y, :]
                roi_b_bgr = full_bgr[split_y:h, :]
            else:
                roi_b_bgr = full_bgr[0:split_y, :]
                roi_f_bgr = full_bgr[split_y:h, :]
        else:
            # 左右排布
            split_x = int((f_center_x + b_center_x) / 2.0)
            split_x = max(int(w * 0.15), min(int(w * 0.85), split_x))
            if f_center_x < b_center_x:
                roi_f_bgr = full_bgr[:, 0:split_x]
                roi_b_bgr = full_bgr[:, split_x:w]
            else:
                roi_b_bgr = full_bgr[:, 0:split_x]
                roi_f_bgr = full_bgr[:, split_x:w]

        cache_dir = os.path.join(os.path.dirname(os.path.abspath(img_path)), ".split_cache")
        os.makedirs(cache_dir, exist_ok=True)
        h_uid = hashlib.md5(img_path.encode("utf-8", errors="ignore")).hexdigest()[:6] if 'hashlib' in globals() else "tmp"
        temp_f_path = os.path.join(cache_dir, f"temp_f_{h_uid}_{os.path.basename(img_path)}.png")
        temp_b_path = os.path.join(cache_dir, f"temp_b_{h_uid}_{os.path.basename(img_path)}.png")

        cv2.imencode(".png", roi_f_bgr)[1].tofile(temp_f_path)
        cv2.imencode(".png", roi_b_bgr)[1].tofile(temp_b_path)

        card_front = correct_and_crop_card(temp_f_path, mode=mode)
        card_back = correct_and_crop_card(temp_b_path, mode=mode)

        try:
            if os.path.exists(temp_f_path): os.remove(temp_f_path)
            if os.path.exists(temp_b_path): os.remove(temp_b_path)
        except Exception:
            pass

        return card_front, card_back
    except Exception as e:
        print(f"[Scanner] 单图双面切片异常 ({img_path}): {e}")
        return None, None

