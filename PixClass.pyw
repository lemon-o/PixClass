#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片分类程序
基于 PyQt5 的图片拖拽分类工具
"""

import sys
import os
import json
import shutil
from pathlib import Path
from typing import Optional

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *


# ─────────────────────────────────────────────
#  全局配置与常量
# ─────────────────────────────────────────────
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif', '.ico'}
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.m4v', '.mpg', '.mpeg', '.3gp', '.webm'}
ALL_MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS  # 合并图片和视频扩展名

# 窗口布局持久化键名
KEY_THUMB_SIZE = "thumb_size"
KEY_SPLITTER_SIZES = "splitter_sizes"

EMPTY_FOLDER_TEXT = (
    "点击左上角「打开文件夹」选择媒体目录\n\n"
    "支持图片: JPG / PNG / GIF / BMP / WebP\n"
    "支持视频: MP4 / AVI / MOV / MKV / WebM"
)

NO_MEDIA_TEXT = (
    "未发现媒体文件\n\n"
    "支持的格式: JPG, PNG, GIF, BMP, WebP\n"
    "MP4, AVI, MOV, MKV, WebM"
)

def normalize_path(path: str) -> str:
    """将路径中的正斜杠统一替换为反斜杠（Windows UNC 路径格式）"""
    return path.replace('/', '\\') if path else path

# 自动确定存储路径 (AppData/PixClass/config.json)
if sys.platform == "win32":
    CONFIG_DIR = os.path.join(os.environ.get("APPDATA", ""), "PixClass")
else:
    CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".pixclass")

CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

def save_global_setting(key, value):
    """持久化保存设置"""
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR, exist_ok=True)
    
    data = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except: pass
    
    data[key] = value
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_global_setting(key, default=None):
    """读取持久化设置"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f).get(key, default)
        except: pass
    return default
# 中心化路径
GLOBAL_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".pixclass")
GLOBAL_ORDER_FILE = os.path.join(GLOBAL_CONFIG_DIR, "folder_metadata.json")
# 缩略图缓存上限
THUMBNAIL_CACHE_LIMIT = 500

# 缩略图尺寸默认值/范围
DEFAULT_THUMB_SIZE = 140
MIN_THUMB_SIZE = 80
MAX_THUMB_SIZE = 240

# 界面配色方案
BG_COLOR       = QColor(18, 18, 22)       # 主背景色
PANEL_COLOR    = QColor(26, 26, 32)       # 面板背景色
CARD_COLOR     = QColor(36, 36, 44)       # 卡片背景色
CARD_HOVER     = QColor(99, 179, 237, 60) # 卡片悬停色
ACCENT_COLOR   = QColor(99, 179, 237)     # 主强调色
ACCENT2_COLOR  = QColor(86, 98, 209)    # 次强调色
TEXT_PRIMARY   = QColor(230, 230, 240)    # 主要文字色
TEXT_SECONDARY = QColor(140, 140, 160)    # 次要文字色
DROP_HIGHLIGHT = QColor(99, 179, 237, 80) # 拖拽高亮色
DROP_BORDER    = QColor(99, 179, 237)     # 拖拽边框色
SELECT_COLOR   = QColor(99, 179, 237, 60) # 选中高亮色
SELECT_BORDER  = QColor(99, 179, 237)     # 选中边框色


# ─────────────────────────────────────────────
#  缩略图加载线程（异步加载，防止界面卡顿）
# ─────────────────────────────────────────────
class ThumbnailLoader(QThread):
    """图片缩略图加载线程（支持EXIF方向）"""
    thumbnail_ready = pyqtSignal(str, QPixmap)

    def __init__(self, path: str, size: int):
        super().__init__()
        self.path = path
        self.size = size

    def run(self):
        if self.isInterruptionRequested():
            return
        try:
            # 使用 QImageReader 而不是 QImage，以便读取 EXIF 方向
            reader = QImageReader(self.path)
            reader.setAutoTransform(True)  # 关键：自动应用 EXIF 方向变换
            
            img = reader.read()
            if not img.isNull() and not self.isInterruptionRequested():
                scaled = img.scaled(
                    self.size, self.size,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                self.thumbnail_ready.emit(self.path, QPixmap.fromImage(scaled))
        except Exception:
            pass

class VideoThumbnailLoader(QThread):
    """视频缩略图加载线程"""
    thumbnail_ready = pyqtSignal(str, QPixmap)

    def __init__(self, path: str, size: int):
        super().__init__()
        self.path = path
        self.size = size

    def run(self):
        if self.isInterruptionRequested():
            return
        try:
            # 尝试提取视频缩略图
            thumbnail = self._extract_thumbnail()
            if not self.isInterruptionRequested():
                self.thumbnail_ready.emit(self.path, thumbnail)
        except Exception as e:
            # 如果失败，使用默认占位图
            if not self.isInterruptionRequested():
                placeholder = self._make_video_placeholder()
                self.thumbnail_ready.emit(self.path, placeholder)
    
    def _extract_thumbnail(self) -> QPixmap:
        """提取视频中间帧作为缩略图"""
        try:
            import cv2
            cap = cv2.VideoCapture(self.path)
            if cap.isOpened():
                # 获取视频总帧数
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                
                if total_frames > 0:
                    # 提取中间帧（1/5 处，避免开头的黑屏或过暗帧）
                    mid_frame = total_frames // 5
                    cap.set(cv2.CAP_PROP_POS_FRAMES, mid_frame)
                    ret, frame = cap.read()
                    
                    if ret:
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        h, w, ch = frame.shape
                        bytes_per_line = ch * w
                        qimage = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
                        scaled = qimage.scaled(self.size, self.size,
                                            Qt.KeepAspectRatio,
                                            Qt.SmoothTransformation)
                        cap.release()
                        return QPixmap.fromImage(scaled)
                else:
                    # 无法获取帧数，回退到第一帧
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = cap.read()
                    if ret:
                        # ... 处理同上
                        pass
            cap.release()
        except ImportError:
            pass
        
        return self._make_video_placeholder()
    
    def _make_video_placeholder(self) -> QPixmap:
        """创建视频文件占位图"""
        s = self.size
        px = QPixmap(s, s)
        px.fill(Qt.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing)
        
        # 背景
        p.setBrush(QBrush(QColor(50, 50, 65)))
        p.setPen(Qt.NoPen)
        path = QPainterPath()
        path.addRoundedRect(2, 2, s - 4, s - 4, 8, 8)
        p.drawPath(path)
        
        # 电影胶片图标
        p.setPen(QPen(QColor(100, 100, 120), 1.5))
        film_x = s // 4
        film_y = s // 3
        film_w = s // 2
        film_h = s // 3
        p.drawRoundedRect(film_x, film_y, film_w, film_h, 4, 4)
        
        # 绘制胶片孔
        hole_size = max(2, s // 20)
        for i in range(3):
            p.drawEllipse(film_x + 5 + i * (film_w - 10) // 2, 
                         film_y + 5, hole_size, hole_size)
            p.drawEllipse(film_x + 5 + i * (film_w - 10) // 2,
                         film_y + film_h - 8, hole_size, hole_size)
        
        # 播放按钮
        p.setBrush(QBrush(QColor(200, 200, 220, 180)))
        p.drawEllipse(s // 2 - 12, s // 2 - 12, 24, 24)
        p.setBrush(QBrush(QColor(50, 50, 65)))
        triangle = [
            QPoint(s // 2 - 3, s // 2 - 6),
            QPoint(s // 2 - 3, s // 2 + 6),
            QPoint(s // 2 + 6, s // 2)
        ]
        p.drawPolygon(triangle)
        
        p.end()
        return px

class FolderThumbnailLoader(QThread):
    """文件夹封面异步加载线程"""
    thumbnail_ready = pyqtSignal(str, QPixmap)

    def __init__(self, folder_path: str, cover_path: str, size: int, base_px: QPixmap):
        super().__init__()
        self.folder_path = folder_path
        self.cover_path = cover_path
        self.size = size
        self.base_px = base_px.copy()

    def run(self):
        try:
            s = self.size
            cover_size = int(s * 0.58)
            
            # 判断封面文件类型
            ext = Path(self.cover_path).suffix.lower()
            
            if ext in VIDEO_EXTENSIONS:
                # 如果是视频，使用视频缩略图加载器
                cover_px = self._load_video_thumbnail(cover_size)
            else:
                # 图片则正常加载
                cover_px = self._load_image_thumbnail(cover_size)
            
            if cover_px is None or cover_px.isNull():
                self.thumbnail_ready.emit(self.folder_path, self.base_px)
                return

            result = self.base_px.copy()
            p = QPainter(result)
            p.setRenderHint(QPainter.Antialiasing)
            cw, ch = cover_px.width(), cover_px.height()
            cx = (s - cw) // 2
            cy = int(s * 0.28)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(0, 0, 0, 80)))
            p.drawRoundedRect(cx + 3, cy + 3, cw, ch, 4, 4)
            p.setBrush(QBrush(QColor(240, 240, 245)))
            p.drawRoundedRect(cx - 2, cy - 2, cw + 4, ch + 4, 4, 4)
            p.drawPixmap(cx, cy, cover_px)
            p.end()
            self.thumbnail_ready.emit(self.folder_path, result)
        except Exception:
            self.thumbnail_ready.emit(self.folder_path, self.base_px)

    def _scale_and_crop_image(self, source_image, cover_size: int) -> QPixmap:
        """统一的缩放裁剪逻辑：放大填充后居中裁剪"""
        iw, ih = source_image.width(), source_image.height()
        if iw > 0 and ih > 0:
            # 放大填充：计算缩放比例，使图片完全覆盖 cover_size×cover_size
            scale = max(cover_size / iw, cover_size / ih)
            scaled_w = int(iw * scale)
            scaled_h = int(ih * scale)
            
            # 缩放到覆盖尺寸
            scaled_img = source_image.scaled(scaled_w, scaled_h,
                                            Qt.IgnoreAspectRatio, 
                                            Qt.SmoothTransformation)
            
            # 居中裁剪
            crop_x = (scaled_w - cover_size) // 2
            crop_y = (scaled_h - cover_size) // 2
            cropped = scaled_img.copy(crop_x, crop_y, cover_size, cover_size)
            
            return QPixmap.fromImage(cropped)
        return QPixmap()

    def _load_image_thumbnail(self, cover_size: int) -> Optional[QPixmap]:
        """加载图片缩略图"""
        try:
            reader = QImageReader(self.cover_path)
            reader.setAutoTransform(True)
            img = reader.read()
            
            if img.isNull():
                return None

            return self._scale_and_crop_image(img, cover_size)
        except Exception:
            pass
        return None

    def _load_video_thumbnail(self, cover_size: int) -> Optional[QPixmap]:
        """加载视频缩略图，使用 1/5 处帧"""
        try:
            import cv2
            
            cap = cv2.VideoCapture(self.cover_path)
            if not cap.isOpened():
                cap.release()
                return self._make_video_placeholder(cover_size)
            
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            if total_frames > 0:
                target_frame = total_frames // 5
                if target_frame < 1:
                    target_frame = 1
                
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                ret, frame = cap.read()
                
                if not ret:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    for i in range(target_frame):
                        ret, frame = cap.read()
                        if not ret:
                            break
                
                if ret and frame is not None and frame.size > 0:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = frame_rgb.shape
                    bytes_per_line = ch * w
                    qimage = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
                    cap.release()
                    return self._scale_and_crop_image(qimage, cover_size)
            else:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()
                if ret and frame is not None and frame.size > 0:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = frame_rgb.shape
                    bytes_per_line = ch * w
                    qimage = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
                    cap.release()
                    return self._scale_and_crop_image(qimage, cover_size)
                    
            cap.release()
            
        except ImportError:
            pass
        except Exception:
            pass
        
        return self._make_video_placeholder(cover_size)

    def _make_video_placeholder(self, size: int) -> QPixmap:
        """创建视频文件占位图"""
        px = QPixmap(size, size)
        px.fill(Qt.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing)
        
        # 背景
        p.setBrush(QBrush(QColor(50, 50, 65)))
        p.setPen(Qt.NoPen)
        path = QPainterPath()
        path.addRoundedRect(2, 2, size - 4, size - 4, 4, 4)
        p.drawPath(path)
        
        # 电影胶片图标
        p.setPen(QPen(QColor(100, 100, 120), 1.0))
        film_x = size // 4
        film_y = size // 3
        film_w = size // 2
        film_h = size // 3
        p.drawRoundedRect(film_x, film_y, film_w, film_h, 3, 3)
        
        # 绘制胶片孔
        hole_size = max(2, size // 20)
        for i in range(3):
            p.drawEllipse(film_x + 5 + i * (film_w - 10) // 2, 
                         film_y + 5, hole_size, hole_size)
            p.drawEllipse(film_x + 5 + i * (film_w - 10) // 2,
                         film_y + film_h - 8, hole_size, hole_size)
        
        # 播放按钮
        p.setBrush(QBrush(QColor(200, 200, 220, 180)))
        p.drawEllipse(size // 2 - 10, size // 2 - 10, 20, 20)
        p.setBrush(QBrush(QColor(50, 50, 65)))
        triangle = [
            QPoint(size // 2 - 3, size // 2 - 5),
            QPoint(size // 2 - 3, size // 2 + 5),
            QPoint(size // 2 + 5, size // 2)
        ]
        p.drawPolygon(triangle)
        
        p.end()
        return px
    
# ─────────────────────────────────────────────
#  文件/文件夹数据项类
# ─────────────────────────────────────────────
class FileItem:
    def __init__(self, path: str, is_dir: bool):
        self.path = normalize_path(path)
        self.name = os.path.basename(self.path)
        self.is_dir = is_dir
        self.thumbnail: Optional[QPixmap] = None
        self.loading = False

    def is_image(self) -> bool:
        # 判断是否为支持的媒体文件（图片或视频）
        return not self.is_dir and Path(self.path).suffix.lower() in ALL_MEDIA_EXTENSIONS

    def is_video(self) -> bool:
        # 判断是否为视频文件
        return not self.is_dir and Path(self.path).suffix.lower() in VIDEO_EXTENSIONS


# ─────────────────────────────────────────────
#  中心化管理所有文件夹的元数据
# ─────────────────────────────────────────────
class OrderManager:
    """中心化管理所有文件夹的元数据，不产生本地 json 文件"""
    _cached_data = None 

    def __init__(self, folder_path: str):
        self.folder_path = normalize_path(os.path.abspath(folder_path))
        if OrderManager._cached_data is None:
            self._load_all()

    def _load_all(self):
        OrderManager._cached_data = load_global_setting("folder_metadata", {})

    def _save_all(self):
        save_global_setting("folder_metadata", OrderManager._cached_data)

    def add_image(self, filename: str):
        """记录媒体文件顺序（用于封面选择）"""
        if self.folder_path not in OrderManager._cached_data:
            OrderManager._cached_data[self.folder_path] = []
        
        if filename not in OrderManager._cached_data[self.folder_path]:
            OrderManager._cached_data[self.folder_path].append(filename)
            self._save_all()

    def remove_image(self, filename: str):
        """移除文件记录"""
        if self.folder_path in OrderManager._cached_data:
            if filename in OrderManager._cached_data[self.folder_path]:
                OrderManager._cached_data[self.folder_path].remove(filename)
                self._save_all()

    def clear_records(self):
        """清除该文件夹的所有记录"""
        if self.folder_path in OrderManager._cached_data:
            OrderManager._cached_data[self.folder_path] = []
            self._save_all()

    def sync_with_filesystem(self):
        """同步记录与实际文件系统：移除不存在的文件记录"""
        if self.folder_path not in OrderManager._cached_data:
            return
        
        valid_records = []
        for filename in OrderManager._cached_data[self.folder_path]:
            full_path = os.path.join(self.folder_path, filename)
            if os.path.exists(full_path):
                valid_records.append(filename)
        
        if len(valid_records) != len(OrderManager._cached_data[self.folder_path]):
            OrderManager._cached_data[self.folder_path] = valid_records
            self._save_all()

    def get_cover(self) -> Optional[str]:
        """
        获取封面：先找记录中的媒体文件，再找物理文件
        支持图片和视频作为封面
        """
        # 先同步记录，移除不存在的文件
        self.sync_with_filesystem()
        
        folder_data = OrderManager._cached_data.get(self.folder_path, [])
        
        # 1. 优先从历史记录中查找存在的媒体文件
        for name in folder_data:
            full = os.path.join(self.folder_path, name)
            if os.path.exists(full):
                ext = Path(full).suffix.lower()
                if ext in ALL_MEDIA_EXTENSIONS:
                    return full
        
        # 2. 兜底逻辑：扫描文件夹
        try:
            if os.path.exists(self.folder_path):
                image_files = []
                video_files = []
                
                with os.scandir(self.folder_path) as it:
                    for entry in it:
                        if entry.is_file() and not entry.name.startswith('.'):
                            ext = Path(entry.name).suffix.lower()
                            if ext in IMAGE_EXTENSIONS:
                                image_files.append(entry.path)
                            elif ext in VIDEO_EXTENSIONS:
                                video_files.append(entry.path)
                
                if image_files:
                    image_files.sort()
                    return image_files[0]
                elif video_files:
                    video_files.sort()
                    return video_files[0]
                    
        except Exception:
            pass
            
        return None

    def remove_image(self, filename: str):
        if self.folder_path in OrderManager._cached_data:
            if filename in OrderManager._cached_data[self.folder_path]:
                OrderManager._cached_data[self.folder_path].remove(filename)
                self._save_all()

    def get_current_cover(self) -> Optional[str]:
        """获取当前有效的封面（不触发同步）"""
        folder_data = OrderManager._cached_data.get(self.folder_path, [])
        for name in folder_data:
            full = os.path.join(self.folder_path, name)
            if os.path.exists(full):
                ext = Path(full).suffix.lower()
                if ext in ALL_MEDIA_EXTENSIONS:
                    return full
        return None
# ─────────────────────────────────────────────
#  操作历史：支持撤销 / 重做文件移动
# ─────────────────────────────────────────────
class MoveRecord:
    """记录一次批量移动操作（支持整批撤销 / 重做）"""
    def __init__(self, moves: list[tuple[str, str]]):
        # moves: [(src_path, dst_path), ...]  dst_path 为移动后的实际完整路径
        self.moves = moves


class CopyRecord:
    """记录一次批量复制操作（撤销时删除已复制的文件）"""
    def __init__(self, copies: list[tuple[str, str]]):
        # copies: [(原src, 已复制到的dst), ...]  撤销时删除 dst
        self.copies = copies

class PasteRecord:
    """记录一次粘贴操作（支持撤销/重做）"""
    def __init__(self, copies: list[tuple[str, str]], is_cut: bool):
        # copies: [(src_path, dst_path), ...] 粘贴操作创建的每个文件
        # is_cut: True=剪切粘贴, False=复制粘贴
        self.copies = copies
        self.is_cut = is_cut

class ActionHistory:
    """轻量撤销/重做栈，跟踪文件移动和粘贴操作"""
    MAX_DEPTH = 50  # 最多保留 50 步历史

    def __init__(self):
        self._undo_stack: list = []  # 可以存储 MoveRecord 或 PasteRecord
        self._redo_stack: list = []

    def push(self, record):
        """记录一步操作，清空 redo 栈"""
        self._undo_stack.append(record)
        if len(self._undo_stack) > self.MAX_DEPTH:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def pop_undo(self):
        if self._undo_stack:
            rec = self._undo_stack.pop()
            self._redo_stack.append(rec)
            return rec
        return None

    def pop_redo(self):
        if self._redo_stack:
            rec = self._redo_stack.pop()
            self._undo_stack.append(rec)
            return rec
        return None

    def clear(self):
        self._undo_stack.clear()
        self._redo_stack.clear()


# ─────────────────────────────────────────────
#  文件列表数据模型
# ─────────────────────────────────────────────

class ScannerThread(QThread):
    """后台扫描线程，用于流式发现文件"""
    item_found = pyqtSignal(object)  # 信号：发现一个 FileItem
    finished = pyqtSignal()         # 信号：扫描完成

    def __init__(self, folder_path, dirs_only=False, files_only=False):
        super().__init__()
        self.folder_path = folder_path
        self.dirs_only = dirs_only
        self.files_only = files_only
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        try:
            # 使用 os.scandir 提高遍历效率
            with os.scandir(self.folder_path) as it:
                # 为了保持基本的视觉顺序，先读取并排序
                entries = sorted(list(it), key=lambda e: e.name.lower())
                
                for entry in entries:
                    if not self._is_running:
                        break
                    
                    # 过滤逻辑
                    if entry.name.startswith('.') or entry.name.startswith('_imgclass'):
                        continue
                        
                    try:
                        item = None
                        if entry.is_dir():
                            if not self.files_only:
                                item = FileItem(entry.path, True)
                        else:
                            if not self.dirs_only:
                                ext = Path(entry.name).suffix.lower()
                                if ext in ALL_MEDIA_EXTENSIONS:
                                    item = FileItem(entry.path, False)
                        
                        if item:
                            # 关键：通过信号发送给 Model
                            self.item_found.emit(item)
                            # 极其微小的延迟可以让 UI 刷新更平滑，不至于瞬间阻塞主线程
                            self.msleep(1) 
                            
                    except OSError:
                        continue
        except Exception as e:
            print(f"扫描出错: {e}")
        
        self.finished.emit()

class BatchThumbnailLoader(QThread):
    """批量加载缩略图线程（用于文件数 ≤ 500 时）"""
    thumbnails_ready = pyqtSignal(list)  # 信号：[(path, pixmap), ...]

    def __init__(self, items: list, size: int):
        super().__init__()
        self.items = items  # FileItem 列表
        self.size = size

    def run(self):
        results = []
        for item in self.items:
            # 支持外部中断（刷新/导航时安全退出）
            if self.isInterruptionRequested():
                break
            if item.is_dir:
                continue  # 文件夹由 FolderThumbnailLoader 单独处理
            
            try:
                if item.is_video():
                    # 视频缩略图
                    px = self._extract_video_thumbnail(item.path)
                    if px is None:
                        px = self._make_video_placeholder()
                else:
                    # 图片缩略图
                    reader = QImageReader(item.path)
                    reader.setAutoTransform(True)
                    img = reader.read()
                    if not img.isNull():
                        scaled = img.scaled(
                            self.size, self.size,
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation
                        )
                        px = QPixmap.fromImage(scaled)
                    else:
                        px = self._make_image_placeholder()
                
                if px:
                    results.append((item.path, px))
            except Exception:
                pass
        
        self.thumbnails_ready.emit(results)
    
    def _extract_video_thumbnail(self, path: str) -> Optional[QPixmap]:
        """提取视频中间帧作为缩略图"""
        try:
            import cv2
            cap = cv2.VideoCapture(path)
            if cap.isOpened():
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                
                if total_frames > 0:
                    mid_frame = total_frames // 5
                    cap.set(cv2.CAP_PROP_POS_FRAMES, mid_frame)
                    ret, frame = cap.read()
                    
                    if ret:
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        h, w, ch = frame.shape
                        bytes_per_line = ch * w
                        qimage = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
                        scaled = qimage.scaled(self.size, self.size,
                                            Qt.KeepAspectRatio,
                                            Qt.SmoothTransformation)
                        cap.release()
                        return QPixmap.fromImage(scaled)
            cap.release()
        except ImportError:
            pass
        
        return None
    
    def _make_video_placeholder(self) -> QPixmap:
        """创建视频文件占位图"""
        s = self.size
        px = QPixmap(s, s)
        px.fill(Qt.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing)
        
        p.setBrush(QBrush(QColor(50, 50, 65)))
        p.setPen(Qt.NoPen)
        path = QPainterPath()
        path.addRoundedRect(2, 2, s - 4, s - 4, 8, 8)
        p.drawPath(path)
        
        p.setPen(QPen(QColor(100, 100, 120), 1.5))
        film_x = s // 4
        film_y = s // 3
        film_w = s // 2
        film_h = s // 3
        p.drawRoundedRect(film_x, film_y, film_w, film_h, 4, 4)
        
        hole_size = max(2, s // 20)
        for i in range(3):
            p.drawEllipse(film_x + 5 + i * (film_w - 10) // 2, 
                         film_y + 5, hole_size, hole_size)
            p.drawEllipse(film_x + 5 + i * (film_w - 10) // 2,
                         film_y + film_h - 8, hole_size, hole_size)
        
        p.setBrush(QBrush(QColor(200, 200, 220, 180)))
        p.drawEllipse(s // 2 - 12, s // 2 - 12, 24, 24)
        p.setBrush(QBrush(QColor(50, 50, 65)))
        triangle = [
            QPoint(s // 2 - 3, s // 2 - 6),
            QPoint(s // 2 - 3, s // 2 + 6),
            QPoint(s // 2 + 6, s // 2)
        ]
        p.drawPolygon(triangle)
        
        p.end()
        return px
    
    def _make_image_placeholder(self) -> QPixmap:
        """创建图片占位图"""
        s = self.size
        px = QPixmap(s, s)
        px.fill(Qt.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(QColor(50, 50, 65)))
        p.setPen(Qt.NoPen)
        path = QPainterPath()
        path.addRoundedRect(2, 2, s - 4, s - 4, 8, 8)
        p.drawPath(path)
        p.setPen(QPen(QColor(100, 100, 120), 1.5))
        cx, cy = s // 2, s // 2
        iw, ih = s // 3, s // 4
        p.drawRoundedRect(cx - iw // 2, cy - ih // 2, iw, ih, 3, 3)
        pts_l = [QPoint(cx - iw // 2, cy + ih // 2 - 2),
                 QPoint(cx - iw // 8, cy),
                 QPoint(cx + iw // 6, cy + ih // 4)]
        pts_r = [QPoint(cx + iw // 6, cy + ih // 4),
                 QPoint(cx + iw // 3, cy + ih // 8),
                 QPoint(cx + iw // 2, cy + ih // 2 - 2)]
        for pts in [pts_l, pts_r]:
            for i in range(len(pts) - 1):
                p.drawLine(pts[i], pts[i + 1])
        p.drawEllipse(cx - iw // 4, cy - ih // 2 + 4, iw // 5, iw // 5)
        p.end()
        return px
    
class FileListModel(QAbstractListModel):
    ITEM_ROLE = Qt.UserRole + 1
    scan_finished = pyqtSignal()
    first_item_found = pyqtSignal()
    all_thumbnails_loaded = pyqtSignal()  # 新增：所有缩略图加载完成信号

    def __init__(self):
        super().__init__()
        self.items: list[FileItem] = []
        self._scanner: Optional[ScannerThread] = None
        self._batch_loader: Optional[BatchThumbnailLoader] = None
        self._first_item_emitted = False

    def rowCount(self, parent=QModelIndex()):
        return len(self.items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.items):
            return QVariant()
        item = self.items[index.row()]
        if role == Qt.DisplayRole:
            return item.name
        if role == self.ITEM_ROLE:
            return item
        return QVariant()

    def flags(self, index):
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.isValid():
            item = self.items[index.row()]
            if item.is_image():
                base |= Qt.ItemIsDragEnabled
            if item.is_dir:
                base |= Qt.ItemIsDropEnabled
        return base

    def supportedDropActions(self):
        return Qt.MoveAction

    def mimeTypes(self):
        return ['application/x-imgclassifier-items']

    def mimeData(self, indexes):
        paths = []
        for idx in indexes:
            item = self.items[idx.row()]
            if item.is_image():
                paths.append(item.path)
        mime = QMimeData()
        mime.setData('application/x-imgclassifier-items',
                     '\n'.join(paths).encode('utf-8'))
        return mime

    def load_folder_sync(self, folder_path: str, dirs_only: bool = False, files_only: bool = False):
        """同步加载文件夹（用于导航时快速刷新）"""
        # 1. 停止之前的扫描任务
        if self._scanner and self._scanner.isRunning():
            self._scanner.stop()
            self._scanner.wait(2000)  # 最多等2秒，避免死锁
            self._scanner = None

        if self._batch_loader and self._batch_loader.isRunning():
            # 标记停止，不阻塞等待（等待会导致主线程死锁）
            self._batch_loader.requestInterruption()
            self._batch_loader.wait(500)  # 最多等500ms
            self._batch_loader = None

        # 2. 一次性清空并加载所有项目
        self.beginResetModel()
        self.items.clear()
        
        try:
            # 直接同步遍历文件夹
            items_to_add = []
            with os.scandir(folder_path) as it:
                for entry in it:
                    if entry.name.startswith('.') or entry.name.startswith('_imgclass'):
                        continue
                    
                    try:
                        item = None
                        if entry.is_dir():
                            if not files_only:
                                item = FileItem(entry.path, True)
                        else:
                            if not dirs_only:
                                ext = Path(entry.name).suffix.lower()
                                if ext in ALL_MEDIA_EXTENSIONS:
                                    item = FileItem(entry.path, False)
                        
                        if item:
                            items_to_add.append(item)
                    except OSError:
                        continue
            
            # 排序：文件夹在前，按名称排序
            dirs = [item for item in items_to_add if item.is_dir]
            files = [item for item in items_to_add if not item.is_dir]
            dirs.sort(key=lambda x: x.name.lower())
            files.sort(key=lambda x: x.name.lower())
            
            self.items = dirs + files
            
        except Exception as e:
            print(f"同步扫描出错: {e}")
            
        self.endResetModel()
        
        # 发射信号
        self.first_item_found.emit()
        self.scan_finished.emit()

    def load_folder_async(self, folder_path: str, dirs_only: bool = False, files_only: bool = False):
        """异步流式加载文件夹（用于初始打开大文件夹）"""
        # 1. 停止之前的扫描任务
        if self._scanner and self._scanner.isRunning():
            self._scanner.stop()
            self._scanner.wait()

        # 2. 清空当前视图
        self.beginResetModel()
        self.items.clear()
        self.endResetModel()

        # 重置首次发射标记
        self._first_item_emitted = False

        # 3. 创建并启动扫描线程
        self._scanner = ScannerThread(folder_path, dirs_only, files_only)
        self._scanner.item_found.connect(self._handle_item_found)
        self._scanner.finished.connect(self._on_scan_finished_for_batch)
        self._scanner.start()

    # --- 流式加载核心逻辑 ---
    def load_folder(self, folder_path: str, dirs_only: bool = False, files_only: bool = False):
        """默认使用异步流式加载（保持向后兼容）"""
        self.load_folder_async(folder_path, dirs_only, files_only)

    def _handle_item_found(self, item: 'FileItem'):
        """处理线程发回的每一个项"""
        insert_idx = len(self.items)
        if item.is_dir:
            for i, existing in enumerate(self.items):
                if not existing.is_dir or existing.name.lower() > item.name.lower():
                    insert_idx = i
                    break
        else:
            for i, existing in enumerate(self.items):
                if not existing.is_dir and existing.name.lower() > item.name.lower():
                    insert_idx = i
                    break

        self.beginInsertRows(QModelIndex(), insert_idx, insert_idx)
        self.items.insert(insert_idx, item)
        self.endInsertRows()

        # 如果是第一个项目，发射信号
        if not self._first_item_emitted:
            self._first_item_emitted = True
            self.first_item_found.emit()

    def _on_scan_finished_for_batch(self):
        """扫描完成后，判断是否需要批量加载缩略图"""
        self.scan_finished.emit()
        
        # 统计媒体文件数量（非文件夹）
        media_count = sum(1 for item in self.items if not item.is_dir)
        
        if 0 < media_count <= 500:
            # 文件数 ≤ 500，启动批量加载
            media_items = [item for item in self.items if not item.is_dir]
            if media_items:
                self._batch_loader = BatchThumbnailLoader(media_items, MAX_THUMB_SIZE)
                self._batch_loader.thumbnails_ready.connect(self._on_batch_thumbnails_ready)
                self._batch_loader.start()
        else:
            # 文件数 > 500 或为 0，直接发射完成信号
            self.all_thumbnails_loaded.emit()
    
    def _on_batch_thumbnails_ready(self, results: list):
        """批量缩略图加载完成"""
        # 将结果存入 items 的 thumbnail 属性
        path_to_pixmap = {path: px for path, px in results}
        
        for item in self.items:
            if not item.is_dir and item.path in path_to_pixmap:
                item.thumbnail = path_to_pixmap[item.path]
                item.loading = False
        
        # 通知视图刷新
        self.all_thumbnails_loaded.emit()
        
        # 触发数据变更，让代理重新绘制
        if self.items:
            top_left = self.index(0)
            bottom_right = self.index(len(self.items) - 1)
            self.dataChanged.emit(top_left, bottom_right, [self.ITEM_ROLE])

    # --- 其他辅助方法 ---

    def get_item(self, index: QModelIndex) -> Optional['FileItem']:
        if index.isValid() and 0 <= index.row() < len(self.items):
            return self.items[index.row()]
        return None

    def refresh_item(self, path: str):
        for i, item in enumerate(self.items):
            if item.path == path:
                item.thumbnail = None
                idx = self.index(i)
                self.dataChanged.emit(idx, idx)
                break

    def remove_item(self, path: str):
        for i, item in enumerate(self.items):
            if item.path == path:
                self.beginRemoveRows(QModelIndex(), i, i)
                self.items.pop(i)
                self.endRemoveRows()
                return


# ─────────────────────────────────────────────
#  自定义绘制代理：负责绘制每个网格项
# ─────────────────────────────────────────────
class FileItemDelegate(QStyledItemDelegate):
    def __init__(self, model: FileListModel, thumb_size: int, parent=None):
        super().__init__(parent)
        self.model = model
        self.thumb_size = thumb_size
        self._thumb_cache: dict[str, QPixmap] = {}  # 缩略图缓存
        self._loaders: list[QThread] = []            # 所有加载线程列表
        self._loading_folders: set[str] = set()      # 正在加载封面的文件夹路径
        self._drop_target: Optional[str] = None      # 拖拽目标文件夹路径
        self._MAX_CONCURRENT_LOADERS = 4             # 最大并发加载线程数，防止滚动卡顿
        
        # 固定使用最大尺寸生成所有占位图
        self._placeholder_folder = self._make_folder_icon_at_size(MAX_THUMB_SIZE)
        self._placeholder_image = self._make_image_placeholder_at_size(MAX_THUMB_SIZE)
        self._placeholder_video = self._make_video_placeholder_at_size(MAX_THUMB_SIZE)

        # 定期清理已结束的线程
        self._cleanup_timer = QTimer()
        self._cleanup_timer.setInterval(2000)
        self._cleanup_timer.timeout.connect(self._cleanup_loaders)
        self._cleanup_timer.start()

    def _cleanup_loaders(self):
        self._loaders = [l for l in self._loaders if l.isRunning()]

    def stop_all_loaders(self):
        """停止所有正在运行的缩略图加载线程（刷新/导航时调用，防止卡死）"""
        for loader in self._loaders:
            if loader.isRunning():
                loader.requestInterruption()
        # 非阻塞：让线程自行退出，不等待，避免主线程卡死
        self._loaders.clear()
        self._loading_folders.clear()

    def set_drop_target(self, path: Optional[str]):
        self._drop_target = path

    def set_thumb_size(self, size: int):
        """设置缩略图显示尺寸，占位图始终使用最大尺寸，无需重新生成"""
        self.thumb_size = size
        # 占位图不需要重新生成，因为总是最大尺寸，绘制时会自动缩放

    def invalidate_cache(self, path: str):
        """失效指定路径的缓存"""
        keys = [k for k in self._thumb_cache if path in k]
        for k in keys:
            del self._thumb_cache[k]
        self._loading_folders.discard(path)

    def _make_folder_icon_at_size(self, s: int) -> QPixmap:
        """按指定尺寸绘制文件夹图标"""
        px = QPixmap(s, s)
        px.fill(Qt.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing)

        # 阴影
        shadow = QRadialGradient(s * 0.5, s * 0.72, s * 0.45)
        shadow.setColorAt(0, QColor(0, 0, 0, 60))
        shadow.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(shadow))
        p.setPen(Qt.NoPen)
        p.drawEllipse(int(s * 0.05), int(s * 0.45), int(s * 0.9), int(s * 0.35))

        # 文件夹背部
        back_color = QColor(80, 100, 160)
        p.setBrush(QBrush(back_color))
        p.setPen(Qt.NoPen)
        tab_rect = QRect(int(s * 0.08), int(s * 0.22), int(s * 0.38), int(s * 0.12))
        path_tab = QPainterPath()
        path_tab.addRoundedRect(tab_rect.x(), tab_rect.y(),
                                 tab_rect.width(), tab_rect.height(), 4, 4)
        p.drawPath(path_tab)

        body = QRect(int(s * 0.06), int(s * 0.30), int(s * 0.88), int(s * 0.52))
        path_body = QPainterPath()
        path_body.addRoundedRect(body.x(), body.y(), body.width(), body.height(), 6, 6)

        # 渐变填充
        grad = QLinearGradient(body.x(), body.y(), body.x(), body.bottom())
        grad.setColorAt(0, QColor(100, 130, 210))
        grad.setColorAt(1, QColor(65, 90, 170))
        p.setBrush(QBrush(grad))
        p.drawPath(path_body)

        # 高光
        shine = QLinearGradient(body.x(), body.y(), body.x(), body.y() + body.height() * 0.4)
        shine.setColorAt(0, QColor(255, 255, 255, 50))
        shine.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(shine))
        p.drawPath(path_body)

        p.end()
        return px

    def _make_image_placeholder_at_size(self, s: int) -> QPixmap:
        """按指定尺寸绘制图片占位图"""
        px = QPixmap(s, s)
        px.fill(Qt.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(QColor(50, 50, 65)))
        p.setPen(Qt.NoPen)
        path = QPainterPath()
        path.addRoundedRect(2, 2, s - 4, s - 4, 8, 8)
        p.drawPath(path)
        # 图片图标
        p.setPen(QPen(QColor(100, 100, 120), 1.5))
        cx, cy = s // 2, s // 2
        iw, ih = s // 3, s // 4
        p.drawRoundedRect(cx - iw // 2, cy - ih // 2, iw, ih, 3, 3)
        # 山形图案
        pts_l = [QPoint(cx - iw // 2, cy + ih // 2 - 2),
                 QPoint(cx - iw // 8, cy),
                 QPoint(cx + iw // 6, cy + ih // 4)]
        pts_r = [QPoint(cx + iw // 6, cy + ih // 4),
                 QPoint(cx + iw // 3, cy + ih // 8),
                 QPoint(cx + iw // 2, cy + ih // 2 - 2)]
        for pts in [pts_l, pts_r]:
            for i in range(len(pts) - 1):
                p.drawLine(pts[i], pts[i + 1])
        # 太阳
        p.drawEllipse(cx - iw // 4, cy - ih // 2 + 4, iw // 5, iw // 5)
        p.end()
        return px

    def _make_video_placeholder_at_size(self, s: int) -> QPixmap:
        """按指定尺寸绘制视频占位图"""
        px = QPixmap(s, s)
        px.fill(Qt.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing)
        
        # 背景
        p.setBrush(QBrush(QColor(50, 50, 65)))
        p.setPen(Qt.NoPen)
        path = QPainterPath()
        path.addRoundedRect(2, 2, s - 4, s - 4, 8, 8)
        p.drawPath(path)
        
        # 电影胶片图标
        p.setPen(QPen(QColor(100, 100, 120), 1.5))
        film_x = s // 4
        film_y = s // 3
        film_w = s // 2
        film_h = s // 3
        p.drawRoundedRect(film_x, film_y, film_w, film_h, 4, 4)
        
        # 绘制胶片孔
        hole_size = max(2, s // 20)
        for i in range(3):
            p.drawEllipse(film_x + 5 + i * (film_w - 10) // 2, 
                         film_y + 5, hole_size, hole_size)
            p.drawEllipse(film_x + 5 + i * (film_w - 10) // 2,
                         film_y + film_h - 8, hole_size, hole_size)
        
        # 播放按钮
        p.setBrush(QBrush(QColor(200, 200, 220, 180)))
        p.drawEllipse(s // 2 - 12, s // 2 - 12, 24, 24)
        p.setBrush(QBrush(QColor(50, 50, 65)))
        triangle = [
            QPoint(s // 2 - 3, s // 2 - 6),
            QPoint(s // 2 - 3, s // 2 + 6),
            QPoint(s // 2 + 6, s // 2)
        ]
        p.drawPolygon(triangle)
        
        p.end()
        return px

    def _make_folder_icon(self) -> QPixmap:
        """兼容旧接口，返回最大尺寸的文件夹图标"""
        return self._placeholder_folder

    def _make_image_placeholder(self) -> QPixmap:
        """兼容旧接口，返回最大尺寸的图片占位图"""
        return self._placeholder_image

    def _build_folder_thumbnail(self, item: FileItem, index: QModelIndex) -> QPixmap:
        """获取文件夹缩略图"""
        cache_key = f"folder:{item.path}"
        
        # 检查缓存
        if cache_key in self._thumb_cache:
            cached = self._thumb_cache[cache_key]
            return self._scale_pixmap(cached)

        # 已在加载中，返回占位图
        if item.path in self._loading_folders:
            return self._scale_pixmap(self._placeholder_folder)

        # 获取封面路径
        om = OrderManager(item.path)
        cover_path = om.get_cover()

        if not cover_path:
            # 无封面：缓存最大尺寸占位图
            self._thumb_cache[cache_key] = self._placeholder_folder
            return self._scale_pixmap(self._placeholder_folder)

        # 启动后台线程异步加载封面
        item.loading = True
        self._loading_folders.add(item.path)
        loader = FolderThumbnailLoader(item.path, cover_path, MAX_THUMB_SIZE, self._placeholder_folder)

        def on_folder_ready(folder_path, px):
            self._thumb_cache[f"folder:{folder_path}"] = px
            self._loading_folders.discard(folder_path)
            # 更新模型
            for i, it in enumerate(self.model.items):
                if it.path == folder_path:
                    it.loading = False
                    idx = self.model.index(i)
                    self.model.dataChanged.emit(idx, idx)
                    break

        loader.thumbnail_ready.connect(on_folder_ready)
        loader.start()
        self._loaders.append(loader)

        return self._scale_pixmap(self._placeholder_folder)

    def _get_media_thumbnail(self, item: FileItem, index: QModelIndex) -> QPixmap:
        """获取媒体文件缩略图"""
        cache_key = f"media:{item.path}"

        # 检查内存缓存
        if cache_key in self._thumb_cache:
            return self._scale_pixmap(self._thumb_cache[cache_key])
        
        # 检查 item 自带的 thumbnail（批量加载的结果）
        if item.thumbnail is not None and not item.thumbnail.isNull():
            # 存入缓存
            self._thumb_cache[cache_key] = item.thumbnail
            return self._scale_pixmap(item.thumbnail)

        if not item.loading:
            # 限制并发加载线程数，防止滚动时启动过多线程导致卡顿
            active_count = sum(1 for l in self._loaders if l.isRunning())
            if active_count >= self._MAX_CONCURRENT_LOADERS:
                # 达到上限，返回占位图，等下次重绘时再尝试
                if item.is_video():
                    return self._scale_pixmap(self._placeholder_video)
                else:
                    return self._scale_pixmap(self._placeholder_image)

            item.loading = True

            # 始终按最大尺寸加载
            if item.is_video():
                loader = VideoThumbnailLoader(item.path, MAX_THUMB_SIZE)
            else:
                loader = ThumbnailLoader(item.path, MAX_THUMB_SIZE)

            def on_ready(path, px, _loader=loader):
                # 若该线程已被中断（刷新/导航触发），忽略结果
                if _loader.isInterruptionRequested():
                    return
                self._thumb_cache[f"media:{path}"] = px
                item.loading = False
                item.thumbnail = px  # 同时存入 item
                if index.isValid():
                    model = index.model()
                    if model:
                        model.dataChanged.emit(index, index)

            loader.thumbnail_ready.connect(on_ready)
            loader.start()
            self._loaders.append(loader)

        # 返回占位图
        if item.is_video():
            return self._scale_pixmap(self._placeholder_video)
        else:
            return self._scale_pixmap(self._placeholder_image)

    def _scale_pixmap(self, pixmap: QPixmap) -> QPixmap:
        """将高分辨率图片缩放到当前显示尺寸"""
        if pixmap.width() == self.thumb_size and pixmap.height() == self.thumb_size:
            return pixmap
        return pixmap.scaled(self.thumb_size, self.thumb_size,
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation)
    
    def sizeHint(self, option, index):
        # 项尺寸
        cell = self.thumb_size + 40
        return QSize(cell, cell)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        # 绘制单个项
        item: FileItem = index.data(FileListModel.ITEM_ROLE)
        if not item:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        r = option.rect
        pad = 6
        card_rect = r.adjusted(pad, pad, -pad, -pad)

        is_selected = bool(option.state & QStyle.State_Selected)  # 选中状态
        is_hovered = item.path == self._drop_target # 拖拽悬停
        is_mouse_over = bool(option.state & QStyle.State_MouseOver) # 鼠标悬停

        # 卡片背景色
        if is_hovered:
            bg = CARD_HOVER
        elif is_selected:
            bg = SELECT_COLOR
        elif is_mouse_over:
            bg = CARD_HOVER
        else:
            bg = CARD_COLOR

        path = QPainterPath()
        path.addRoundedRect(card_rect.x(), card_rect.y(),
                             card_rect.width(), card_rect.height(), 10, 10)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(bg))
        painter.drawPath(path)

        # 边框
        if is_selected:
            painter.setPen(QPen(SELECT_BORDER, 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

        # 缩略图区域
        thumb_area_h = card_rect.height() - 30
        thumb_y = card_rect.y() + 6
        thumb_x = card_rect.x() + (card_rect.width() - self.thumb_size) // 2

        if item.is_dir:
            px = self._build_folder_thumbnail(item, index)
        else:
            px = self._get_media_thumbnail(item, index)  # 新代码

        # 居中绘制缩略图
        if px and not px.isNull():
            draw_x = card_rect.x() + (card_rect.width() - px.width()) // 2
            draw_y = thumb_y + (thumb_area_h - px.height()) // 2
            # 裁剪到卡片范围内
            painter.setClipPath(path)
            painter.drawPixmap(draw_x, draw_y, px)
            painter.setClipping(False)

        # 文件名标签区域
        label_rect = QRect(
            card_rect.x() + 4,
            card_rect.bottom() - 26,
            card_rect.width() - 8,
            24
        )

        # 标签背景
        label_bg = QPainterPath()
        label_bg.addRoundedRect(label_rect.x(), label_rect.y(),
                                 label_rect.width(), label_rect.height(), 5, 5)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 100)))
        painter.drawPath(label_bg)

        # 文件名文字
        font = QFont("Microsoft YaHei", 8) if sys.platform == "win32" else QFont("PingFang SC", 8)
        font.setWeight(QFont.Medium)
        painter.setFont(font)
        painter.setPen(QPen(TEXT_PRIMARY))
        fm = QFontMetrics(font)
        name = item.name
        elided = fm.elidedText(name, Qt.ElideMiddle, label_rect.width() - 6)
        painter.drawText(label_rect, Qt.AlignCenter | Qt.AlignVCenter, elided)

        painter.restore()


# ─────────────────────────────────────────────
#  图片网格视图：自定义拖拽和双击逻辑
# ─────────────────────────────────────────────
class ImageGridView(QListView):
    folder_entered = pyqtSignal(str)          # 进入文件夹信号
    image_opened = pyqtSignal(str)            # 打开图片信号
    items_moved = pyqtSignal(list, str)       # 图片移动信号(路径列表,目标文件夹)
    items_copied = pyqtSignal(list, str)      # 图片复制信号(路径列表,目标文件夹) ← 新增
    cut_requested = pyqtSignal(list)          # 剪切信号(路径列表)
    copy_requested = pyqtSignal(list)         # 复制信号(路径列表)
    paste_requested = pyqtSignal()            # 粘贴信号
    new_folder_requested = pyqtSignal()       # 新建文件夹信号
    rename_requested = pyqtSignal(str)        # 重命名信号(路径)
    is_folder_panel: bool = False             # 标记是否为右侧文件夹面板
    thumb_size_changed = pyqtSignal(int)      # 缩略图大小变化信号

    def __init__(self, model: FileListModel, delegate: FileItemDelegate, parent=None):
        super().__init__(parent)
        self.file_model = model
        self.file_delegate = delegate

        self.setModel(model)
        self.setItemDelegate(delegate)
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setMouseTracking(True)
        self.setSpacing(4)
        self.setUniformItemSizes(True)
        self.setWordWrap(False)
        self.viewport().setAcceptDrops(True)

        self._drag_start: Optional[QPoint] = None
        self._drop_index: Optional[QModelIndex] = None

        # 橡皮筋多选相关
        self._rubber_band: Optional[QRubberBand] = None
        self._rubber_origin: Optional[QPoint] = None
        self._rubber_selecting: bool = False

        # 界面样式
        self.setStyleSheet(f"""
            QListView {{
                background-color: {BG_COLOR.name()};
                border: none;
                outline: none;
            }}
            QListView::item {{
                border: none;
                padding: 0px;
            }}
            QScrollBar:vertical {{
                background: {PANEL_COLOR.name()};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: #555566;
                border-radius: 4px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #777788;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                background: none;
                height: 0px;
                border: none;
                subcontrol-origin: margin;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
            QScrollBar:horizontal {{
                background: {PANEL_COLOR.name()};
                height: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:horizontal {{
                background: #555566;
                border-radius: 4px;
                min-width: 30px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: #777788;
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                background: none;
                width: 0px;
                border: none;
                subcontrol-origin: margin;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: none;
            }}
        """)

    def update_thumb_size(self, size: int):
        """更新缩略图尺寸（实时）"""
        self.file_delegate.set_thumb_size(size)
        cell = size + 40
        self.setGridSize(QSize(cell, cell))
        # 强制立即重新布局，不需要延迟
        self.doItemsLayout()
        self.viewport().update()

    def wheelEvent(self, event):
        """处理 Ctrl+滚轮调整缩略图大小"""
        if event.modifiers() & Qt.ControlModifier:
            # 计算新的缩略图大小
            delta = event.angleDelta().y()
            if delta > 0:
                new_size = min(MAX_THUMB_SIZE, self.file_delegate.thumb_size + 10)
            else:
                new_size = max(MIN_THUMB_SIZE, self.file_delegate.thumb_size - 10)
            
            if new_size != self.file_delegate.thumb_size:
                self.thumb_size_changed.emit(new_size)
            event.accept()
        else:
            super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event):
        # 双击事件：进入文件夹/打开图片
        index = self.indexAt(event.pos())
        if index.isValid():
            item: FileItem = index.data(FileListModel.ITEM_ROLE)
            if item:
                if item.is_dir:
                    self.folder_entered.emit(item.path)
                else:
                    self.image_opened.emit(item.path)
        super().mouseDoubleClickEvent(event)

    def _is_blank_area(self, pos: QPoint) -> bool:
        """判断坐标是否处于空白区域（图片与图片之间的间隔，或无图片的空白）"""
        index = self.indexAt(pos)
        return not index.isValid()

    def _find_main_window(self):
        """向上查找主窗口"""
        parent = self.parent()
        while parent:
            if isinstance(parent, MainWindow):
                return parent
            parent = parent.parent()
        return None

    def mousePressEvent(self, event):
        """鼠标点击时自动获取焦点，并处理侧键"""
        # 先设置焦点
        self.setFocus()
        
        # 处理鼠标侧键
        if event.button() == Qt.XButton1:  # 侧键后退
            main_win = self._find_main_window()
            if main_win:
                main_win._go_up()
            event.accept()
            return
        elif event.button() == Qt.XButton2:  # 侧键前进
            main_win = self._find_main_window()
            if main_win:
                main_win._go_history_back()
            event.accept()
            return
        
        if event.button() == Qt.LeftButton:
            if self._is_blank_area(event.pos()):
                # 点击空白区域：开始橡皮筋框选
                self._rubber_origin = event.pos()
                self._rubber_selecting = True
                self._drag_start = None
                if self._rubber_band is None:
                    self._rubber_band = QRubberBand(QRubberBand.Rectangle, self.viewport())
                self._rubber_band.setGeometry(QRect(self._rubber_origin, QSize()))
                self._rubber_band.show()
                # 清除已有选中（除非按住 Ctrl/Shift）
                if not (event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)):
                    self.clearSelection()
            else:
                # 点击了图片：记录拖拽起始
                self._rubber_selecting = False
                self._drag_start = event.pos()
                super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # 橡皮筋框选中
        if self._rubber_selecting and self._rubber_origin is not None:
            rect = QRect(self._rubber_origin, event.pos()).normalized()
            self._rubber_band.setGeometry(rect)
            # 根据框选矩形更新选中项
            scroll_rect = QRect(
                rect.x() + self.horizontalScrollBar().value(),
                rect.y() + self.verticalScrollBar().value(),
                rect.width(), rect.height()
            )
            sel = QItemSelection()
            for i in range(self.file_model.rowCount()):
                idx = self.file_model.index(i)
                item: FileItem = idx.data(FileListModel.ITEM_ROLE)
                
                # 根据面板类型决定选择什么
                if self.is_folder_panel:
                    # 右侧栏：只选择文件夹
                    if not item or not item.is_dir:
                        continue
                else:
                    # 左侧栏：只选择图片/视频文件
                    if not item or item.is_dir:
                        continue
                        
                vr = self.visualRect(idx)
                if vr.intersects(rect):
                    sel.select(idx, idx)
            
            mode = QItemSelectionModel.ClearAndSelect if not (
                event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)
            ) else QItemSelectionModel.Select
            self.selectionModel().select(sel, mode)
            return

        # 处理拖拽操作
        if (event.buttons() & Qt.LeftButton and
                self._drag_start and
                (event.pos() - self._drag_start).manhattanLength() > 10):

            selected = self.selectedIndexes()
            drag_items = []
            for idx in selected:
                item: FileItem = idx.data(FileListModel.ITEM_ROLE)
                if item:
                    # 根据面板类型决定可以拖拽什么
                    if self.is_folder_panel:
                        # 右侧栏：可以拖拽文件夹（虽然实际很少用）
                        if item.is_dir:
                            drag_items.append(item)
                    else:
                        # 左侧栏：只能拖拽图片/视频
                        if item.is_image():
                            drag_items.append(item)

            if drag_items:
                drag = QDrag(self)
                
                # 强制生成拖拽数据
                paths = [i.path for i in drag_items]
                mime = QMimeData()
                mime.setData('application/x-imgclassifier-items',
                            '\n'.join(paths).encode('utf-8'))
                drag.setMimeData(mime)

                # 拖拽图标
                first = drag_items[0]
                if first.is_dir:
                    # 文件夹使用文件夹图标
                    px = self.file_delegate._build_folder_thumbnail(first, selected[0])
                else:
                    # 文件使用缩略图
                    px = self.file_delegate._get_media_thumbnail(first, selected[0])
                    
                if px and not px.isNull():
                    scaled = px.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    badge = QPixmap(scaled.width() + 4, scaled.height() + 4)
                    badge.fill(Qt.transparent)
                    bp = QPainter(badge)
                    bp.setRenderHint(QPainter.Antialiasing)
                    bp.setOpacity(0.85)
                    bp.drawPixmap(2, 2, scaled)
                    if len(drag_items) > 1:
                        bp.setOpacity(1.0)
                        bp.setBrush(QBrush(ACCENT_COLOR))
                        bp.setPen(Qt.NoPen)
                        bp.drawEllipse(badge.width() - 18, 0, 18, 18)
                        bp.setPen(QPen(Qt.white))
                        bp.setFont(QFont("Arial", 8, QFont.Bold))
                        bp.drawText(QRect(badge.width() - 18, 0, 18, 18),
                                    Qt.AlignCenter, str(len(drag_items)))
                    bp.end()
                    drag.setPixmap(badge)
                    drag.setHotSpot(QPoint(badge.width() // 2, badge.height() // 2))

                # 执行拖拽
                drag.exec_(Qt.MoveAction)
                self._drag_start = None
                return

        # 鼠标悬停：更新拖拽高亮
        index = self.indexAt(event.pos())
        if index.isValid():
            item: FileItem = index.data(FileListModel.ITEM_ROLE)
            if item and item.is_dir:
                self.file_delegate.set_drop_target(item.path)
                self.viewport().update()
                super().mouseMoveEvent(event)
                return
        self.file_delegate.set_drop_target(None)
        self.viewport().update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._rubber_selecting:
            self._rubber_selecting = False
            if self._rubber_band:
                self._rubber_band.hide()
            self._rubber_origin = None
            return
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event):
        # 拖拽进入：验证数据类型
        if event.mimeData().hasFormat('application/x-imgclassifier-items'):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        # 拖拽移动：判断目标是否为文件夹
        if not event.mimeData().hasFormat('application/x-imgclassifier-items'):
            event.ignore()
            return
        index = self.indexAt(event.pos())
        if index.isValid():
            item: FileItem = index.data(FileListModel.ITEM_ROLE)
            if item and item.is_dir:
                self.file_delegate.set_drop_target(item.path)
                self.viewport().update()
                event.acceptProposedAction()
                return
        self.file_delegate.set_drop_target(None)
        self.viewport().update()
        event.ignore()

    def dragLeaveEvent(self, event):
        # 拖拽离开：清除高亮
        self.file_delegate.set_drop_target(None)
        self.viewport().update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        # 拖拽释放：执行文件移动
        self.file_delegate.set_drop_target(None)
        if not event.mimeData().hasFormat('application/x-imgclassifier-items'):
            event.ignore()
            return

        index = self.indexAt(event.pos())
        if not index.isValid():
            event.ignore()
            return

        target_item: FileItem = index.data(FileListModel.ITEM_ROLE)
        if not target_item or not target_item.is_dir:
            event.ignore()
            return

        raw = event.mimeData().data('application/x-imgclassifier-items').data()
        paths = raw.decode('utf-8').strip().split('\n')
        paths = [p for p in paths if p and os.path.isfile(p)]

        if paths:
            self.items_moved.emit(paths, target_item.path)
            event.acceptProposedAction()
        else:
            event.ignore()

        self.viewport().update()

    def contextMenuEvent(self, event):
        """右键菜单：有选中项时显示剪切/复制/新建，空白处显示新建/粘贴"""
        index = self.indexAt(event.pos())
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: #1e1e28;
                color: #e6e6f0;
                border: 1px solid #3a3a50;
                border-radius: 6px;
                padding: 4px 0;
                font-size: 13px;
                font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
            }}
            QMenu::item {{
                padding: 6px 20px 6px 12px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background: rgba(99,179,237,30);
                color: {ACCENT_COLOR.name()};
            }}
            QMenu::separator {{
                height: 1px;
                background: #2a2a36;
                margin: 3px 8px;
            }}
        """)

        selected_indexes = self.selectedIndexes()
        selected_paths = []
        for idx in selected_indexes:
            item = idx.data(FileListModel.ITEM_ROLE)
            if item:
                selected_paths.append(item.path)

        if index.isValid() and selected_paths:
            # 选中了项目：显示剪切/复制/新建文件夹/重命名
            if self.is_folder_panel:
                act_new = menu.addAction("📁  新建文件夹")
                act_new.triggered.connect(self.new_folder_requested.emit)
                menu.addSeparator()
            act_cut = menu.addAction("✂  剪切")
            act_cut.triggered.connect(lambda: self.cut_requested.emit(selected_paths))
            act_copy = menu.addAction("⎘  复制")
            act_copy.triggered.connect(lambda: self.copy_requested.emit(selected_paths))
            # 仅单选时允许重命名
            if len(selected_paths) == 1:
                menu.addSeparator()
                act_rename = menu.addAction("✏  重命名\tF2")
                act_rename.triggered.connect(lambda: self.rename_requested.emit(selected_paths[0]))
        else:
            # 空白处
            act_new = menu.addAction("📁  新建文件夹")
            act_new.triggered.connect(self.new_folder_requested.emit)
            
            # 修改：无论左侧还是右侧，空白处都显示粘贴选项
            menu.addSeparator()
            act_paste = menu.addAction("📋  粘贴")
            act_paste.triggered.connect(self.paste_requested.emit)

        menu.exec_(event.globalPos())

    def _trigger_rename(self):
        """F2 触发：重命名当前选中的第一个项目"""
        indexes = self.selectedIndexes()
        if len(indexes) == 1:
            item = indexes[0].data(FileListModel.ITEM_ROLE)
            if item:
                self.rename_requested.emit(item.path)

    def leaveEvent(self, event):
        """鼠标离开视图时清除高亮"""
        self.file_delegate.set_drop_target(None)
        self.viewport().update()
        super().leaveEvent(event)

# ─────────────────────────────────────────────
#  路径导航栏（面包屑）
# ─────────────────────────────────────────────
class BreadcrumbBar(QWidget):
    path_selected = pyqtSignal(str)  # 路径选择信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 4, 8, 4)
        self._layout.setSpacing(2)
        self._layout.addStretch()
        self.setStyleSheet(f"background: {PANEL_COLOR.name()}; border-radius: 6px;")
        self._crumbs: list[tuple[str, str]] = []  # (显示名称, 路径)

    def set_path(self, path: str, root: str):
        # 清空现有导航
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 构建导航路径
        rel = os.path.relpath(path, os.path.dirname(root))
        parts = []
        cur = path
        while True:
            parts.insert(0, (os.path.basename(cur) or cur, cur))
            if cur == root or os.path.dirname(cur) == cur:
                break
            if os.path.dirname(cur) == os.path.dirname(root):
                break
            cur = os.path.dirname(cur)
            if cur == root:
                parts.insert(0, (os.path.basename(root) or root, root))
                break

        # 确保根目录在最前
        if not parts or parts[0][1] != root:
            parts.insert(0, (os.path.basename(root) or root, root))

        for i, (label, p) in enumerate(parts):
            if i > 0:
                sep = QLabel("›")
                sep.setStyleSheet(f"color: {TEXT_SECONDARY.name()}; font-size: 14px;")
                self._layout.insertWidget(self._layout.count() - 1, sep)

            btn = QToolButton()
            btn.setText(label)
            is_last = (i == len(parts) - 1)
            color = TEXT_PRIMARY.name() if is_last else TEXT_SECONDARY.name()
            btn.setStyleSheet(f"""
                QToolButton {{
                    color: {color};
                    background: transparent;
                    border: none;
                    font-size: 12px;
                    padding: 2px 4px;
                    font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
                }}
                QToolButton:hover {{
                    color: {ACCENT_COLOR.name()};
                    background: rgba(99,179,237,15);
                    border-radius: 4px;
                }}
            """)
            btn.setCursor(Qt.PointingHandCursor)
            _p = p
            btn.clicked.connect(lambda checked, pp=_p: self.path_selected.emit(pp))
            self._layout.insertWidget(self._layout.count() - 1, btn)


# ─────────────────────────────────────────────
#  主窗口
# ─────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.current_path: Optional[str] = None   # 当前路径
        self.root_path: Optional[str] = None      # 根路径
        self.history: list[str] = []             # 浏览历史
        self.action_history = ActionHistory()    # 文件移动撤销/重做历史
        self._clipboard_paths: list[str] = []    # 剪贴板文件路径
        self._clipboard_is_cut: bool = False     # True=剪切, False=复制

        self.setWindowTitle("PixClass")
        # 初始化阶段先隐藏窗口，避免半加载状态显示
        self.setUpdatesEnabled(False)
        self.hide()

        self._setup_ui()
        self._apply_global_style()

        # 安装事件过滤器来监听焦点变化
        self.grid_view.installEventFilter(self)
        self.folder_view.installEventFilter(self)
        self.installEventFilter(self) 

        # 等事件循环启动后，再执行初始化并显示窗口
        QTimer.singleShot(0, self._finish_startup)

    def _finish_startup(self):
        """UI全部构建完成后再显示主窗口"""
        self._load_last_session()

        self.setUpdatesEnabled(True)
        self.showMaximized()
        self.raise_()
        self.activateWindow()

    def eventFilter(self, obj, event):
        """监听视图焦点变化、鼠标侧键"""
        if event.type() == QEvent.FocusIn:
            if obj == self.grid_view:
                # 左侧获得焦点，清除右侧选中
                self.folder_view.clearSelection()
            elif obj == self.folder_view:
                # 右侧获得焦点，清除左侧选中
                self.grid_view.clearSelection()
        
        # 处理鼠标侧键
        elif event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.XButton1:  # 侧键后退（通常是下方侧键）
                self._go_up()
                return True
            elif event.button() == Qt.XButton2:  # 侧键前进（通常是上方侧键）
                self._go_history_back()
                return True
        
        return super().eventFilter(obj, event)
    
    def _apply_global_style(self):
        # 全局样式
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {BG_COLOR.name()};
            }}
            QToolBar {{
                background-color: {PANEL_COLOR.name()};
                border: none;
                border-bottom: 1px solid #2a2a36;
                spacing: 4px;
                padding: 4px 8px;
            }}
            QToolButton {{
                background: transparent;
                border: none;
                border-radius: 6px;
                padding: 6px 10px;
                color: {TEXT_PRIMARY.name()};
                font-size: 13px;
                font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
            }}
            QToolButton:hover {{
                background: rgba(99,179,237,20);
                color: {ACCENT_COLOR.name()};
            }}
            QToolButton:pressed {{
                background: rgba(99,179,237,40);
            }}
            QStatusBar {{
                background: {PANEL_COLOR.name()};
                color: {TEXT_SECONDARY.name()};
                border-top: 1px solid #2a2a36;
                font-size: 11px;
                font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
            }}
            QSlider::groove:horizontal {{
                background: #333344;
                height: 4px;
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {ACCENT_COLOR.name()};
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }}
            QSlider::sub-page:horizontal {{
                background: {ACCENT_COLOR.name()};
                border-radius: 2px;
            }}
        """)

    def _setup_ui(self):
        # 设置窗口图标（透明背景）
        try:
            # 优先使用 PNG 格式（支持透明）
            png_icon = './icon/PixClass.png'
            if os.path.exists(png_icon):
                self.setWindowIcon(QIcon(png_icon))
            else:
                # 回退到 ICO
                ico_icon = './icon/PixClass.ico'
                if os.path.exists(ico_icon):
                    self.setWindowIcon(QIcon(ico_icon))
                else:
                    # 创建默认透明图标
                    self.setWindowIcon(self._create_transparent_icon())
        except Exception:
            pass
        # 中心控件
        central = QWidget()
        central.setStyleSheet(f"background: {BG_COLOR.name()};")
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 工具栏 ──
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        self.addToolBar(toolbar)

        # 打开文件夹按钮
        self.btn_open = QToolButton()
        self.btn_open.setText("📂  打开文件夹")
        self.btn_open.setToolTip("选择图片根目录")
        self.btn_open.setCursor(Qt.PointingHandCursor)
        self.btn_open.setStyleSheet(f"""
            QToolButton {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {ACCENT_COLOR.name()}, stop:1 {ACCENT2_COLOR.name()});
                color: white;
                border-radius: 7px;
                padding: 7px 16px;
                font-weight: bold;
                font-size: 13px;
            }}
            QToolButton:hover {{ opacity: 0.9; }}
        """)
        self.btn_open.clicked.connect(self._open_folder)
        toolbar.addWidget(self.btn_open)
        toolbar.addSeparator()

        # 返回上级按钮
        self.btn_back = QToolButton()
        self.btn_back.setText("◀  返回上级")
        self.btn_back.setEnabled(False)
        self.btn_back.setCursor(Qt.PointingHandCursor)
        self.btn_back.clicked.connect(self._go_up)
        toolbar.addWidget(self.btn_back)

        # 后退按钮
        self.btn_hist_back = QToolButton()
        self.btn_hist_back.setText("↩")
        self.btn_hist_back.setToolTip("后退")
        self.btn_hist_back.setEnabled(False)
        self.btn_hist_back.setCursor(Qt.PointingHandCursor)
        self.btn_hist_back.clicked.connect(self._go_history_back)
        toolbar.addWidget(self.btn_hist_back)

        toolbar.addSeparator()

        # 刷新按钮
        btn_refresh = QToolButton()
        btn_refresh.setText("⟳  刷新")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.clicked.connect(self._refresh)
        toolbar.addWidget(btn_refresh)

        toolbar.addSeparator()

        # 撤销按钮（Ctrl+Z）
        self.btn_undo = QToolButton()
        self.btn_undo.setText("↩  撤销")
        self.btn_undo.setToolTip("撤销上一步移动操作 (Ctrl+Z)")
        self.btn_undo.setCursor(Qt.PointingHandCursor)
        self.btn_undo.setEnabled(False)
        self.btn_undo.clicked.connect(self._undo_move)
        toolbar.addWidget(self.btn_undo)

        # 重做按钮（Ctrl+Y）
        self.btn_redo = QToolButton()
        self.btn_redo.setText("↪  重做")
        self.btn_redo.setToolTip("重做下一步移动操作 (Ctrl+Y)")
        self.btn_redo.setCursor(Qt.PointingHandCursor)
        self.btn_redo.setEnabled(False)
        self.btn_redo.clicked.connect(self._redo_move)
        toolbar.addWidget(self.btn_redo)

        # 快捷键
        QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(self._undo_move)
        QShortcut(QKeySequence("Ctrl+Y"), self).activated.connect(self._redo_move)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self).activated.connect(self._redo_move)

        toolbar.addSeparator()

        # 剪切按钮（Ctrl+X）
        self.btn_cut = QToolButton()
        self.btn_cut.setText("✂  剪切")
        self.btn_cut.setToolTip("剪切选中文件 (Ctrl+X)")
        self.btn_cut.setCursor(Qt.PointingHandCursor)
        self.btn_cut.setEnabled(False)
        self.btn_cut.clicked.connect(self._toolbar_cut)
        toolbar.addWidget(self.btn_cut)

        # 复制按钮（Ctrl+C）
        self.btn_copy = QToolButton()
        self.btn_copy.setText("⎘  复制")
        self.btn_copy.setToolTip("复制选中文件 (Ctrl+C)")
        self.btn_copy.setCursor(Qt.PointingHandCursor)
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self._toolbar_copy)
        toolbar.addWidget(self.btn_copy)

        # 粘贴按钮（Ctrl+V）
        self.btn_paste = QToolButton()
        self.btn_paste.setText("📋  粘贴")
        self.btn_paste.setToolTip("粘贴到当前目录 (Ctrl+V)")
        self.btn_paste.setCursor(Qt.PointingHandCursor)
        self.btn_paste.setEnabled(False)
        self.btn_paste.clicked.connect(self._paste_files)

        toolbar.addWidget(self.btn_paste)

        # 重命名按钮（F2）
        self.btn_rename = QToolButton()
        self.btn_rename.setText("✏  重命名")
        self.btn_rename.setToolTip("重命名选中项目 (F2)")
        self.btn_rename.setCursor(Qt.PointingHandCursor)
        self.btn_rename.setEnabled(False)
        self.btn_rename.clicked.connect(self._toolbar_rename)
        toolbar.addWidget(self.btn_rename)

        QShortcut(QKeySequence("Ctrl+X"), self).activated.connect(self._toolbar_cut)
        QShortcut(QKeySequence("Ctrl+C"), self).activated.connect(self._toolbar_copy)
        QShortcut(QKeySequence("Ctrl+V"), self).activated.connect(self._paste_files)
        QShortcut(QKeySequence(Qt.Key_F2), self).activated.connect(self._toolbar_rename)

        # 伸缩占位
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

        # 缩略图大小标签
        lbl_size = QLabel("缩略图大小")
        lbl_size.setStyleSheet(f"color: {TEXT_SECONDARY.name()}; font-size: 12px; padding: 0 6px;")
        toolbar.addWidget(lbl_size)

        # 缩略图大小滑块
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(MIN_THUMB_SIZE)
        self.slider.setMaximum(MAX_THUMB_SIZE)
        self.slider.setValue(DEFAULT_THUMB_SIZE)
        self.slider.setFixedWidth(130)
        self.slider.setToolTip("调整缩略图大小 (Ctrl+滚轮)")
        self.slider.valueChanged.connect(self._on_thumb_size_changed)  # 实时响应，不需要防抖
        toolbar.addWidget(self.slider)

        toolbar.addSeparator()

        # 数量统计标签
        self.lbl_count = QLabel("0 项")
        self.lbl_count.setStyleSheet(f"color: {TEXT_SECONDARY.name()}; font-size: 12px; padding: 0 8px;")
        toolbar.addWidget(self.lbl_count)

        # ── 中央提示标签（没有打开文件夹时显示） ──
        self.central_label_container = QWidget()
        central_label_layout = QVBoxLayout(self.central_label_container)
        central_label_layout.setContentsMargins(0, 0, 0, 0)
        central_label_layout.setSpacing(0)
        central_label_layout.addStretch()

        self.central_label = QLabel(EMPTY_FOLDER_TEXT)
        self.central_label.setAlignment(Qt.AlignCenter)
        self.central_label.setWordWrap(True)
        self.central_label.setStyleSheet(f"""
            color: {TEXT_SECONDARY.name()};
            font-size: 15px;
            font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
            line-height: 2;
            background: {BG_COLOR.name()};
        """)
        central_label_layout.addWidget(self.central_label)
        central_label_layout.addStretch()

        main_layout.addWidget(self.central_label_container)

        # ── 导航栏 ──
        self.breadcrumb = BreadcrumbBar()
        self.breadcrumb.path_selected.connect(self._navigate_to)
        self.breadcrumb.setFixedHeight(36)
        self.breadcrumb.setVisible(False)  # 初始隐藏
        main_layout.addWidget(self.breadcrumb)

        # ── 左右分栏容器 ──
        self.splitter = QSplitter(Qt.Horizontal)  
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        self.splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background: #2a2a36;
                width: 2px;
            }}
        """)
        self.splitter.setVisible(False)  # 初始隐藏
        main_layout.addWidget(self.splitter, 1)

        # ── 左侧：图片网格 ──
        left_widget = QWidget()
        left_widget.setStyleSheet(f"background: {BG_COLOR.name()};")
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # 使用 QStackedWidget 来管理网格视图和空状态提示
        self.left_stacked = QStackedWidget()
        self.left_stacked.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 创建网格视图页面
        self.file_model = FileListModel()
        self.delegate = FileItemDelegate(self.file_model, DEFAULT_THUMB_SIZE)
        self.grid_view = ImageGridView(self.file_model, self.delegate)
        self.grid_view.thumb_size_changed.connect(self._on_thumb_size_changed)
        cell = DEFAULT_THUMB_SIZE + 40
        self.grid_view.setGridSize(QSize(cell, cell))
        self.grid_view.folder_entered.connect(self._navigate_to)
        self.grid_view.image_opened.connect(self._open_image)
        self.grid_view.items_moved.connect(self._on_items_moved)
        self.grid_view.cut_requested.connect(self._on_cut)
        self.grid_view.copy_requested.connect(self._on_copy)
        self.grid_view.paste_requested.connect(self._paste_files)
        self.grid_view.new_folder_requested.connect(self._create_folder)
        self.grid_view.rename_requested.connect(self._rename_item)
        self.grid_view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.file_model.rowsInserted.connect(self._update_count)
        self.file_model.rowsRemoved.connect(self._update_count)
        self.file_model.modelReset.connect(self._update_count)
        self.file_model.scan_finished.connect(self._on_file_scan_finished)

        # 创建空状态页面（带垂直居中的 label）
        empty_page = QWidget()
        empty_page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        empty_layout = QVBoxLayout(empty_page)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.setSpacing(0)

        empty_layout.addStretch()

        self.empty_label = QLabel()
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet(f"""
            color: {TEXT_SECONDARY.name()};
            font-size: 15px;
            font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
            line-height: 2;
            background: {BG_COLOR.name()};
        """)
        self.empty_label.setText(EMPTY_FOLDER_TEXT)
        empty_layout.addWidget(self.empty_label)

        empty_layout.addStretch()

        # 添加到 stacked widget
        self.left_stacked.addWidget(self.grid_view)  # index 0: 网格视图
        self.left_stacked.addWidget(empty_page)      # index 1: 空状态页面

        # 添加到布局，设置 stretch factor 为 1 使其占据所有剩余空间
        left_layout.addWidget(self.left_stacked, 1)

        self.splitter.addWidget(left_widget)

        # ── 右侧：子文件夹面板 ──
        right_widget = QWidget()
        right_widget.setStyleSheet(f"background: {PANEL_COLOR.name()};")
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # 右侧标题栏
        folder_header = QWidget()
        folder_header.setFixedHeight(36)
        folder_header.setStyleSheet(f"""
            background: {PANEL_COLOR.name()};
            border-bottom: 1px solid #2a2a36;
        """)
        folder_header_layout = QHBoxLayout(folder_header)
        folder_header_layout.setContentsMargins(12, 0, 8, 0)
        folder_header_layout.setSpacing(6)

        folder_title = QLabel("📁  子文件夹")
        folder_title.setStyleSheet(f"""
            color: {TEXT_SECONDARY.name()};
            font-size: 12px;
            font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
            font-weight: bold;
            background: transparent;
        """)
        folder_header_layout.addWidget(folder_title)
        folder_header_layout.addStretch()

        # 新建文件夹按钮（始终显示在右侧标题栏）
        self.btn_create_folder = QToolButton()
        self.btn_create_folder.setText("＋")
        self.btn_create_folder.setToolTip("新建文件夹")
        self.btn_create_folder.setCursor(Qt.PointingHandCursor)
        self.btn_create_folder.setStyleSheet(f"""
            QToolButton {{
                color: {ACCENT_COLOR.name()};
                background: rgba(99,179,237,15);
                border: 1px solid rgba(99,179,237,40);
                border-radius: 5px;
                padding: 2px 8px;
                font-size: 16px;
                font-weight: bold;
            }}
            QToolButton:hover {{
                background: rgba(99,179,237,30);
            }}
        """)
        self.btn_create_folder.clicked.connect(self._create_folder)
        self.btn_create_folder.setEnabled(False)
        folder_header_layout.addWidget(self.btn_create_folder)

        right_layout.addWidget(folder_header)

        # 右侧文件夹网格视图
        self.folder_model = FileListModel()
        self.folder_delegate = FileItemDelegate(self.folder_model, DEFAULT_THUMB_SIZE)
        self.folder_view = ImageGridView(self.folder_model, self.folder_delegate)
        self.folder_view.thumb_size_changed.connect(self._on_thumb_size_changed)
        self.folder_model.first_item_found.connect(self._on_folder_first_item)
        self.folder_model.scan_finished.connect(self._on_folder_scan_finished)
        folder_cell = DEFAULT_THUMB_SIZE + 40
        self.folder_view.setGridSize(QSize(folder_cell, folder_cell))
        self.folder_view.folder_entered.connect(self._navigate_to)
        self.folder_view.image_opened.connect(self._open_image)
        # 拖拽图片到右侧文件夹时也触发 items_moved
        self.folder_view.items_moved.connect(self._on_items_moved)
        self.folder_view.cut_requested.connect(self._on_cut)
        self.folder_view.copy_requested.connect(self._on_copy)
        self.folder_view.paste_requested.connect(self._paste_files)
        self.folder_view.new_folder_requested.connect(self._create_folder)
        self.folder_view.rename_requested.connect(self._rename_item)
        self.folder_view.is_folder_panel = True
        self.folder_view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.folder_view.setStyleSheet(f"""
            QListView {{
                background-color: {PANEL_COLOR.name()};
                border: none;
                outline: none;
            }}
            QListView::item {{
                border: none;
                padding: 0px;
            }}
            QScrollBar:vertical {{
                background: {PANEL_COLOR.name()};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: #555566;
                border-radius: 4px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #777788;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                background: none;
                height: 0px;
                border: none;
                subcontrol-origin: margin;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)
        right_layout.addWidget(self.folder_view, 1)

        # 右侧空提示（无子文件夹时：直接显示新建文件夹按钮）
        self.folder_empty_widget = QWidget()
        self.folder_empty_widget.setStyleSheet("background: transparent;")
        empty_vbox = QVBoxLayout(self.folder_empty_widget)
        empty_vbox.setAlignment(Qt.AlignCenter)
        empty_vbox.setSpacing(0)

        self.btn_create_folder_empty = QPushButton("＋  新建文件夹")
        self.btn_create_folder_empty.setCursor(Qt.PointingHandCursor)
        self.btn_create_folder_empty.setFixedSize(160, 40)
        self.btn_create_folder_empty.setStyleSheet(f"""
            QPushButton {{
                background: rgba(99,179,237,18);
                color: {ACCENT_COLOR.name()};
                border: 1px solid rgba(99,179,237,50);
                border-radius: 8px;
                font-size: 14px;
                font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: rgba(99,179,237,35);
                border: 1px solid {ACCENT_COLOR.name()};
            }}
            QPushButton:pressed {{
                background: rgba(99,179,237,55);
            }}
        """)
        self.btn_create_folder_empty.clicked.connect(self._create_folder)
        empty_vbox.addWidget(self.btn_create_folder_empty, 0, Qt.AlignCenter)

        right_layout.addWidget(self.folder_empty_widget)

        self.splitter.addWidget(right_widget)

        # 恢复保存的分栏位置
        saved_sizes = load_global_setting(KEY_SPLITTER_SIZES)
        if saved_sizes and isinstance(saved_sizes, list) and len(saved_sizes) == 2:
            self.splitter.setSizes(saved_sizes)
        else:
            self.splitter.setSizes([700, 920])  # 默认值
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)

        # 初始状态隐藏右侧内容
        self.folder_view.setVisible(False)
        self.folder_empty_widget.setVisible(False)

        # 状态栏
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("就绪 — 请打开一个文件夹以开始分类")

    def _load_last_session(self):
        """启动时加载上次访问的目录"""
        # 恢复缩略图大小
        saved_thumb_size = load_global_setting(KEY_THUMB_SIZE, DEFAULT_THUMB_SIZE)
        if saved_thumb_size != self.slider.value():
            self.slider.blockSignals(True)
            self.slider.setValue(saved_thumb_size)
            self.slider.blockSignals(False)
            self.grid_view.update_thumb_size(saved_thumb_size)
            self.folder_view.update_thumb_size(saved_thumb_size)
        
        # 恢复上次访问的目录
        last = load_global_setting("last_root_path")
        if last:
            last = normalize_path(last)
        if last and os.path.exists(last):
            self.root_path = last
            self._navigate_to(last, use_async=True)
            self.status.showMessage(f"已恢复上次会话: {last}")

    def _on_splitter_moved(self, pos, index):
        """分栏位置变化时保存"""
        if hasattr(self, 'splitter') and self.splitter:
            sizes = self.splitter.sizes()
            save_global_setting(KEY_SPLITTER_SIZES, sizes)

    def _on_folder_first_item(self):
        """发现第一个文件夹时立即显示面板"""
        if self.current_path:
            self.folder_view.setVisible(True)
            self.folder_empty_widget.setVisible(False)

    def _on_folder_scan_finished(self):
        """文件夹扫描完成后，更新右侧面板的显示状态"""
        if self.current_path:
            has_folders = self.folder_model.rowCount() > 0
            self.folder_view.setVisible(has_folders)
            self.folder_empty_widget.setVisible(not has_folders)
            self._update_count()

    def _on_file_scan_finished(self):
        """左侧图片扫描完成后更新显示"""
        self._update_count()

    # ──────────────────────────────────────────
    #  槽函数：界面交互逻辑
    # ──────────────────────────────────────────
    def _open_folder(self):
        default_dir = self.root_path if self.root_path and os.path.exists(self.root_path) else ""
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择图片文件夹",
            default_dir,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        if folder:
            self.root_path = folder
            save_global_setting("last_root_path", folder)
            self.history.clear()
            self.action_history.clear()
            self._update_undo_redo_buttons()
            self._navigate_to(folder, use_async=True)  # 首次打开使用异步流式

    def _navigate_to(self, path: str, use_async: bool = False):
        """
        导航到指定路径
        use_async: True 使用流式加载（首次打开），False 使用同步加载（导航刷新）
        """
        path = normalize_path(path)
        if not os.path.exists(path):
            return

        if self.current_path and path != self.current_path:
            self.history.append(self.current_path)
            self.btn_hist_back.setEnabled(True)

        self.current_path = path

        # 断开之前的连接（如果有）
        try:
            self.file_model.all_thumbnails_loaded.disconnect()
        except TypeError:
            pass
        
        # 连接批量加载完成信号
        self.file_model.all_thumbnails_loaded.connect(self._on_all_thumbnails_loaded)

        # ── 左侧：加载图片 ──
        if use_async:
            self.file_model.load_folder_async(path, dirs_only=False, files_only=True)
        else:
            self.file_model.load_folder_sync(path, dirs_only=False, files_only=True)

        self.breadcrumb.set_path(path, self.root_path or path)

        can_go_up = self.root_path and path != self.root_path
        self.btn_back.setEnabled(bool(can_go_up))

        # ── 右侧：加载子文件夹 ──
        if use_async:
            self.folder_model.load_folder_async(path, dirs_only=True, files_only=False)
        else:
            self.folder_model.load_folder_sync(path, dirs_only=True, files_only=False)

        self.btn_create_folder.setEnabled(True)
        
        self.status.showMessage(f"当前目录: {path}")
        self._update_count()  
        self._update_undo_redo_buttons()

        if self.root_path:
            save_global_setting("last_root_path", self.root_path)

    def _on_all_thumbnails_loaded(self):
        """所有缩略图加载完成后刷新视图"""
        self.grid_view.viewport().update()

    def _go_up(self):
        if self.current_path and self.root_path:
            parent = os.path.dirname(self.current_path)
            if parent != self.current_path:
                self._navigate_to(parent, use_async=False)  # 返回上级使用同步

    def _go_history_back(self):
        if self.history:
            prev = self.history.pop()
            self.current_path = None
            self._navigate_to(prev, use_async=False)  # 历史导航使用同步
            if not self.history:
                self.btn_hist_back.setEnabled(False)

    def _refresh(self):
        """刷新当前目录（同时更新 OrderManager 记录）"""
        if self.current_path:
            # 先停止所有正在运行的缩略图加载线程，防止刷新时卡死
            self.delegate.stop_all_loaders()
            self.folder_delegate.stop_all_loaders()

            # 同步当前目录的 OrderManager 记录
            om = OrderManager(self.current_path)
            om.sync_with_filesystem()
            
            # 清除当前目录缓存
            self.delegate.invalidate_cache(self.current_path)
            self.folder_delegate.invalidate_cache(self.current_path)
            
            # 清除所有子文件夹的缓存并同步记录
            try:
                with os.scandir(self.current_path) as it:
                    for entry in it:
                        if entry.is_dir():
                            sub_om = OrderManager(entry.path)
                            sub_om.sync_with_filesystem()
                            self.delegate.invalidate_cache(entry.path)
                            self.folder_delegate.invalidate_cache(entry.path)
            except Exception:
                pass
            
            cur = self.current_path
            self.current_path = None
            self._navigate_to(cur, use_async=False)
            self.status.showMessage("已刷新")

    def _create_folder(self):
        if not self.current_path:
            return

        # ── 自定义深色风格对话框 ──
        dlg = QDialog(self)
        dlg.setWindowTitle("新建文件夹")
        dlg.setModal(True)
        dlg.setFixedWidth(340)
        dlg.setStyleSheet(f"""
            QDialog {{
                background: {PANEL_COLOR.name()};
                color: {TEXT_PRIMARY.name()};
            }}
            QLabel {{
                color: {TEXT_PRIMARY.name()};
                font-size: 13px;
                font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
                background: transparent;
            }}
            QLineEdit {{
                background: {BG_COLOR.name()};
                color: {TEXT_PRIMARY.name()};
                border: 1px solid #3a3a50;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
                font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
                selection-background-color: {ACCENT_COLOR.name()};
            }}
            QLineEdit:focus {{
                border: 1px solid {ACCENT_COLOR.name()};
            }}
            QPushButton {{
                font-size: 13px;
                font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
                border-radius: 6px;
                padding: 6px 20px;
                min-width: 72px;
            }}
            QPushButton#btn_ok {{
                background: {ACCENT_COLOR.name()};
                color: white;
                border: none;
                font-weight: bold;
            }}
            QPushButton#btn_ok:hover {{
                background: {ACCENT2_COLOR.name()};
            }}
            QPushButton#btn_cancel {{
                background: #2a2a36;
                color: {TEXT_PRIMARY.name()};
                border: 1px solid #3a3a50;
            }}
            QPushButton#btn_cancel:hover {{
                background: #3a3a4a;
            }}
        """)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        lbl = QLabel("文件夹名称：")
        layout.addWidget(lbl)

        edit = QLineEdit()
        edit.setPlaceholderText("请输入文件夹名称")
        layout.addWidget(edit)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("btn_cancel")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(btn_cancel)

        btn_ok = QPushButton("确定")
        btn_ok.setObjectName("btn_ok")
        btn_ok.setCursor(Qt.PointingHandCursor)
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_ok)

        layout.addLayout(btn_row)

        edit.setFocus()
        edit.returnPressed.connect(dlg.accept)

        if dlg.exec_() == QDialog.Accepted:
            name = edit.text().strip()
            if name:
                new_path = os.path.join(self.current_path, name)
                try:
                    os.makedirs(new_path, exist_ok=True)
                    cur = self.current_path
                    self.current_path = None
                    self._navigate_to(cur)
                    self.status.showMessage(f"已创建文件夹: {name}")
                except Exception as e:
                    QMessageBox.warning(self, "创建失败", str(e))

    def _on_thumb_size_changed(self, value: int):
        """实时更新缩略图大小"""
        if self.slider.value() != value:
            self.slider.blockSignals(True)
            self.slider.setValue(value)
            self.slider.blockSignals(False)
        
        # 实时更新两个视图
        self.grid_view.update_thumb_size(value)
        self.folder_view.update_thumb_size(value)
        
        # 持久化保存缩略图大小
        save_global_setting(KEY_THUMB_SIZE, value)

    def _apply_thumb_size(self):
        value = getattr(self, '_pending_thumb_size', self.slider.value())
        self.grid_view.update_thumb_size(value)
        self.grid_view.setGridSize(QSize(value + 40, value + 40))
        self.folder_view.update_thumb_size(value)
        self.folder_view.setGridSize(QSize(value + 40, value + 40))

    def _open_image(self, path: str):
        import subprocess
        if sys.platform == 'win32':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.call(['open', path])
        else:
            subprocess.call(['xdg-open', path])

    def _on_items_moved(self, source_paths: list, dest_folder: str):
        """处理图片拖拽移动"""
        order_mgr = OrderManager(dest_folder)
        moved_count = 0
        errors = []
        move_records: list[tuple[str, str]] = []

        dest_was_empty = self._is_folder_empty_of_media(dest_folder)

        for src_path in source_paths:
            filename = os.path.basename(src_path)
            dest_path = os.path.join(dest_folder, filename)

            if os.path.exists(dest_path):
                base, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(dest_path):
                    dest_path = os.path.join(dest_folder, f"{base}_{counter}{ext}")
                    counter += 1

            try:
                shutil.move(src_path, dest_path)
                new_filename = os.path.basename(dest_path)
                order_mgr.add_image(new_filename)
                
                # 从源文件夹的 OrderManager 中移除记录
                src_dir = os.path.dirname(src_path)
                src_om = OrderManager(src_dir)
                src_om.remove_image(filename)
                
                # 增量更新：直接从模型中移除
                self.file_model.remove_item(src_path)
                
                move_records.append((src_path, dest_path))
                moved_count += 1
            except Exception as e:
                errors.append(f"{filename}: {e}")

        if move_records:
            self.action_history.push(MoveRecord(move_records))
            self._update_undo_redo_buttons()

        # 智能刷新目标文件夹
        if dest_was_empty and moved_count > 0:
            self.delegate.invalidate_cache(dest_folder)
            self.folder_delegate.invalidate_cache(dest_folder)
            self.folder_model.refresh_item(dest_folder)
        
        # 如果目标文件夹就是当前目录，添加移入的文件到模型
        if dest_folder == self.current_path:
            for src_path, dest_path in [(src, dst) for src, dst in zip(source_paths, 
                                             [os.path.join(dest_folder, os.path.basename(src)) for src in source_paths])]:
                if os.path.exists(dest_path):
                    item = FileItem(dest_path, False)
                    self._add_item_to_model(item)

        # 检查源文件夹是否变空
        source_dirs = set(os.path.dirname(src) for src in source_paths)
        for src_dir in source_dirs:
            if self._is_folder_empty_of_media(src_dir):
                src_om = OrderManager(src_dir)
                src_om.clear_records()
                self.delegate.invalidate_cache(src_dir)
                self.folder_delegate.invalidate_cache(src_dir)
                self.folder_model.refresh_item(src_dir)

        self._update_count()
        self.folder_view.viewport().update()
        self.grid_view.viewport().update()

        if errors:
            QMessageBox.warning(self, "移动出错",
                                "以下文件移动失败:\n" + "\n".join(errors))

        self.status.showMessage(f"已将 {moved_count} 个文件移入 「{os.path.basename(dest_folder)}」")

    def _is_folder_empty_of_media(self, folder_path: str) -> bool:
        """检查文件夹是否不包含任何媒体文件（图片或视频）"""
        if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
            return True
        
        try:
            with os.scandir(folder_path) as it:
                for entry in it:
                    if entry.is_file() and not entry.name.startswith('.'):
                        ext = Path(entry.name).suffix.lower()
                        if ext in ALL_MEDIA_EXTENSIONS:
                            return False
        except (PermissionError, OSError):
            pass
        
        return True

    def _clear_folder_order_records(self, folder_path: str):
        """清除指定文件夹在 OrderManager 中的记录"""
        try:
            om = OrderManager(folder_path)
            # 获取当前记录
            folder_data = OrderManager._cached_data.get(folder_path, [])
            if folder_data:
                # 清空记录
                OrderManager._cached_data[folder_path] = []
                om._save_all()
        except Exception:
            pass

    def _undo_move(self):
        """撤销上一步操作（支持移动和粘贴）"""
        if not self.action_history.can_undo():
            return
        
        rec = self.action_history.pop_undo()
        if not rec:
            return

        # 根据记录类型处理
        if isinstance(rec, MoveRecord):
            self._undo_move_record(rec)
        elif isinstance(rec, PasteRecord):
            self._undo_paste_record(rec)
        
        self._update_undo_redo_buttons()

    def _undo_move_record(self, rec: MoveRecord):
        """撤销移动操作"""
        errors = []
        affected_dst_dirs: set[str] = set()
        affected_src_dirs: set[str] = set()
        was_empty: dict[str, bool] = {}

        for src_path, dst_path in reversed(rec.moves):
            if not os.path.exists(dst_path):
                errors.append(f"{os.path.basename(dst_path)}: 文件不存在")
                continue

            src_dir = os.path.dirname(src_path)
            dst_dir = os.path.dirname(dst_path)

            if not os.path.exists(src_dir):
                errors.append(f"{os.path.basename(src_path)}: 原文件夹不存在")
                continue

            for d in (src_dir, dst_dir):
                if d not in was_empty:
                    was_empty[d] = self._is_folder_empty_of_media(d)

            restore_path = src_path
            if os.path.exists(restore_path) and restore_path != dst_path:
                base, ext = os.path.splitext(os.path.basename(src_path))
                counter = 1
                while os.path.exists(restore_path):
                    restore_path = os.path.join(src_dir, f"{base}_{counter}{ext}")
                    counter += 1

            try:
                shutil.move(dst_path, restore_path)

                src_om = OrderManager(src_dir)
                dst_om = OrderManager(dst_dir)
                dst_om.remove_image(os.path.basename(dst_path))
                src_om.add_image(os.path.basename(restore_path))

                affected_dst_dirs.add(dst_dir)
                affected_src_dirs.add(src_dir)

                if dst_dir == self.current_path:
                    self.file_model.remove_item(dst_path)

                if src_dir == self.current_path:
                    if os.path.exists(restore_path):
                        item = FileItem(restore_path, False)
                        self._add_item_to_model(item)

            except Exception as e:
                errors.append(f"{os.path.basename(dst_path)}: {e}")

        for d in affected_src_dirs | affected_dst_dirs:
            self._refresh_directory_cache(d, was_empty=was_empty.get(d, False))

        self._update_count()
        self.folder_view.viewport().update()
        self.grid_view.viewport().update()

        if errors:
            QMessageBox.warning(self, "撤销出错", "\n".join(errors))
        else:
            self.status.showMessage(f"已撤销：还原了 {len(rec.moves)} 个文件")

    def _undo_paste_record(self, rec: PasteRecord):
        """撤销粘贴操作（删除粘贴的文件）"""
        errors = []
        affected_dirs: set[str] = set()
        deleted_count = 0

        for src_path, dst_path in rec.copies:
            if not os.path.exists(dst_path):
                continue

            dst_dir = os.path.dirname(dst_path)
            affected_dirs.add(dst_dir)
            
            is_dir = os.path.isdir(dst_path)

            try:
                # 删除粘贴的文件/文件夹
                if is_dir:
                    shutil.rmtree(dst_path)
                else:
                    os.remove(dst_path)
                
                # 从 OrderManager 中移除
                om = OrderManager(dst_dir)
                om.remove_image(os.path.basename(dst_path))
                
                # 从对应的模型中移除
                if dst_dir == self.current_path:
                    if is_dir:
                        # 从右侧文件夹模型中移除
                        self.folder_model.remove_item(dst_path)
                    else:
                        # 从左侧文件模型中移除
                        self.file_model.remove_item(dst_path)
                
                deleted_count += 1
            except Exception as e:
                errors.append(f"{os.path.basename(dst_path)}: {e}")

        # 刷新受影响的目录缓存
        for d in affected_dirs:
            self._refresh_directory_cache(d, was_empty=False)

        self._update_count()
        self.folder_view.viewport().update()
        self.grid_view.viewport().update()

        if errors:
            QMessageBox.warning(self, "撤销出错", "\n".join(errors))
        else:
            self.status.showMessage(f"已撤销：删除了 {deleted_count} 个粘贴的项目")

    def _redo_move(self):
        """重做下一步操作（支持移动和粘贴）"""
        if not self.action_history.can_redo():
            return
        
        rec = self.action_history.pop_redo()
        if not rec:
            return

        # 根据记录类型处理
        if isinstance(rec, MoveRecord):
            self._redo_move_record(rec)
        elif isinstance(rec, PasteRecord):
            self._redo_paste_record(rec)
        
        self._update_undo_redo_buttons()

    def _redo_move_record(self, rec: MoveRecord):
        """重做移动操作"""
        errors = []
        affected_dirs: set[str] = set()
        was_empty: dict[str, bool] = {}

        for src_path, dst_path in rec.moves:
            restore_path = src_path
            if not os.path.exists(restore_path):
                errors.append(f"{os.path.basename(src_path)}: 文件不存在，无法重做")
                continue

            dest_folder = os.path.dirname(dst_path)
            src_dir = os.path.dirname(restore_path)

            if not os.path.exists(dest_folder):
                errors.append(f"目标文件夹不存在: {dest_folder}")
                continue

            for d in (src_dir, dest_folder):
                if d not in was_empty:
                    was_empty[d] = self._is_folder_empty_of_media(d)

            redo_dst = dst_path
            if os.path.exists(redo_dst) and redo_dst != restore_path:
                base, ext = os.path.splitext(os.path.basename(dst_path))
                counter = 1
                while os.path.exists(redo_dst):
                    redo_dst = os.path.join(dest_folder, f"{base}_{counter}{ext}")
                    counter += 1

            try:
                shutil.move(restore_path, redo_dst)

                src_om = OrderManager(src_dir)
                dst_om = OrderManager(dest_folder)
                src_om.remove_image(os.path.basename(restore_path))
                dst_om.add_image(os.path.basename(redo_dst))

                affected_dirs.add(src_dir)
                affected_dirs.add(dest_folder)

                if src_dir == self.current_path:
                    self.file_model.remove_item(restore_path)

                if dest_folder == self.current_path:
                    if os.path.exists(redo_dst):
                        item = FileItem(redo_dst, False)
                        self._add_item_to_model(item)

            except Exception as e:
                errors.append(f"{os.path.basename(restore_path)}: {e}")

        for d in affected_dirs:
            self._refresh_directory_cache(d, was_empty=was_empty.get(d, False))

        self._update_count()
        self.folder_view.viewport().update()
        self.grid_view.viewport().update()

        if errors:
            QMessageBox.warning(self, "重做出错", "\n".join(errors))
        else:
            self.status.showMessage(f"已重做：移动了 {len(rec.moves)} 个文件")

    def _redo_paste_record(self, rec: PasteRecord):
        """重做粘贴操作"""
        errors = []
        affected_dirs: set[str] = set()
        pasted_count = 0

        for src_path, dst_path in rec.copies:
            if not os.path.exists(src_path):
                errors.append(f"{os.path.basename(src_path)}: 源文件不存在")
                continue

            dst_dir = os.path.dirname(dst_path)
            affected_dirs.add(dst_dir)

            # 如果目标已存在，生成新名称
            final_dst = dst_path
            if os.path.exists(final_dst):
                base, ext = os.path.splitext(os.path.basename(dst_path))
                counter = 1
                while os.path.exists(final_dst):
                    final_dst = os.path.join(dst_dir, f"{base} ({counter}){ext}")
                    counter += 1

            try:
                if os.path.isdir(src_path):
                    shutil.copytree(src_path, final_dst)
                    is_dir = True
                else:
                    shutil.copy2(src_path, final_dst)
                    is_dir = False
                
                # 添加到 OrderManager
                om = OrderManager(dst_dir)
                om.add_image(os.path.basename(final_dst))
                
                # 添加到对应的模型
                if dst_dir == self.current_path:
                    if os.path.exists(final_dst):
                        item = FileItem(final_dst, is_dir)
                        if is_dir:
                            # 添加到右侧文件夹模型
                            self._add_item_to_folder_model(item)
                        else:
                            # 添加到左侧文件模型
                            self._add_item_to_model(item)
                
                pasted_count += 1
            except Exception as e:
                errors.append(f"{os.path.basename(src_path)}: {e}")

        # 刷新受影响的目录缓存
        for d in affected_dirs:
            self._refresh_directory_cache(d, was_empty=False)

        self._update_count()
        self.folder_view.viewport().update()
        self.grid_view.viewport().update()

        if errors:
            QMessageBox.warning(self, "重做出错", "\n".join(errors))
        else:
            self.status.showMessage(f"已重做：粘贴了 {pasted_count} 个项目")

    def _add_item_to_folder_model(self, item: FileItem):
        """将单个文件夹项目按排序规则添加到右侧文件夹模型中"""
        items = self.folder_model.items
        
        # 找到正确的插入位置（只处理文件夹）
        insert_idx = len(items)
        if item.is_dir:
            for i, existing in enumerate(items):
                if not existing.is_dir or existing.name.lower() > item.name.lower():
                    insert_idx = i
                    break
        
        self.folder_model.beginInsertRows(QModelIndex(), insert_idx, insert_idx)
        items.insert(insert_idx, item)
        self.folder_model.endInsertRows()

    def _refresh_directory_cache(self, dir_path: str, was_empty: bool):
        """刷新单个目录的缓存：只在空/非空状态发生变化时才 invalidate"""
        if not os.path.exists(dir_path):
            return

        om = OrderManager(dir_path)
        is_empty_now = self._is_folder_empty_of_media(dir_path)

        if is_empty_now:
            # 现在为空 → 清除记录和缓存
            om.clear_records()
            self.delegate.invalidate_cache(dir_path)
            self.folder_delegate.invalidate_cache(dir_path)
        elif was_empty and not is_empty_now:
            # 从空变非空 → 缓存失效，重新加载封面
            self.delegate.invalidate_cache(dir_path)
            self.folder_delegate.invalidate_cache(dir_path)
        # 否则（一直非空）→ 不动缓存，只触发重绘

        self.folder_model.refresh_item(dir_path)

    def _add_item_to_model(self, item: FileItem):
        """将单个项目按排序规则添加到模型中"""
        items = self.file_model.items
        
        # 找到正确的插入位置
        insert_idx = len(items)
        if item.is_dir:
            for i, existing in enumerate(items):
                if not existing.is_dir or existing.name.lower() > item.name.lower():
                    insert_idx = i
                    break
        else:
            for i, existing in enumerate(items):
                if not existing.is_dir and existing.name.lower() > item.name.lower():
                    insert_idx = i
                    break
        
        self.file_model.beginInsertRows(QModelIndex(), insert_idx, insert_idx)
        items.insert(insert_idx, item)
        self.file_model.endInsertRows()

    def _update_undo_redo_buttons(self):
        self.btn_undo.setEnabled(self.action_history.can_undo())
        self.btn_redo.setEnabled(self.action_history.can_redo())

    def _on_selection_changed(self, selected, deselected):
        """选中项变化时更新剪切/复制/重命名按钮状态"""
        # 获取发送信号的视图
        sender = self.sender()
        
        # 检查左侧选中项
        left_indexes = self.grid_view.selectedIndexes()
        # 检查右侧选中项
        right_indexes = self.folder_view.selectedIndexes()
        
        # 确定当前激活的视图（有焦点的）
        focused = QApplication.focusWidget()
        if focused == self.grid_view or focused == self.grid_view.viewport():
            has_sel = bool(left_indexes)
            single_sel = len(left_indexes) == 1
        elif focused == self.folder_view or focused == self.folder_view.viewport():
            has_sel = bool(right_indexes)
            single_sel = len(right_indexes) == 1
        else:
            # 没有焦点时，根据发送者判断
            if sender == self.grid_view.selectionModel():
                has_sel = bool(left_indexes)
                single_sel = len(left_indexes) == 1
            elif sender == self.folder_view.selectionModel():
                has_sel = bool(right_indexes)
                single_sel = len(right_indexes) == 1
            else:
                # 默认检查两个视图
                has_sel = bool(left_indexes) or bool(right_indexes)
                single_sel = (len(left_indexes) + len(right_indexes)) == 1
        
        self.btn_cut.setEnabled(has_sel)
        self.btn_copy.setEnabled(has_sel)
        self.btn_rename.setEnabled(single_sel)

    def _get_focused_view(self):
        """获取当前焦点的视图"""
        focused = QApplication.focusWidget()
        if focused == self.grid_view or focused == self.grid_view.viewport():
            return self.grid_view
        elif focused == self.folder_view or focused == self.folder_view.viewport():
            return self.folder_view
        return None

    def _get_selected_paths(self) -> list:
        paths = []
        for idx in self.grid_view.selectedIndexes():
            item = idx.data(FileListModel.ITEM_ROLE)
            if item:
                paths.append(item.path)
        return paths

    def _toolbar_cut(self):
        """剪切：根据焦点视图获取选中项"""
        focused = QApplication.focusWidget()
        
        if focused == self.folder_view or focused == self.folder_view.viewport():
            paths = []
            for idx in self.folder_view.selectedIndexes():
                item = idx.data(FileListModel.ITEM_ROLE)
                if item:
                    paths.append(item.path)
        else:
            paths = []
            for idx in self.grid_view.selectedIndexes():
                item = idx.data(FileListModel.ITEM_ROLE)
                if item:
                    paths.append(item.path)
        
        if paths:
            self._on_cut(paths)

    def _toolbar_copy(self):
        """复制：根据焦点视图获取选中项"""
        focused = QApplication.focusWidget()
        
        if focused == self.folder_view or focused == self.folder_view.viewport():
            paths = []
            for idx in self.folder_view.selectedIndexes():
                item = idx.data(FileListModel.ITEM_ROLE)
                if item:
                    paths.append(item.path)
        else:
            paths = []
            for idx in self.grid_view.selectedIndexes():
                item = idx.data(FileListModel.ITEM_ROLE)
                if item:
                    paths.append(item.path)
        
        if paths:
            self._on_copy(paths)

    def _toolbar_rename(self):
        """工具栏/F2 触发重命名：取当前焦点视图的单选项"""
        # 确定当前焦点在哪个视图
        focused = QApplication.focusWidget()
        
        if focused == self.grid_view or focused == self.grid_view.viewport():
            indexes = self.grid_view.selectedIndexes()
        elif focused == self.folder_view or focused == self.folder_view.viewport():
            indexes = self.folder_view.selectedIndexes()
        else:
            # 默认：检查两个视图，优先非空的那个
            indexes = self.grid_view.selectedIndexes()
            if not indexes:
                indexes = self.folder_view.selectedIndexes()
        
        if len(indexes) == 1:
            item = indexes[0].data(FileListModel.ITEM_ROLE)
            if item:
                self._rename_item(item.path)
        elif len(indexes) == 0:
            self.status.showMessage("请先选中要重命名的项目", 2000)
        else:
            self.status.showMessage("一次只能重命名一个项目", 2000)

    def _rename_item(self, path: str):
        """重命名对话框，支持文件和文件夹"""
        if not os.path.exists(path):
            return

        old_name = os.path.basename(path)
        is_dir = os.path.isdir(path)
        parent_dir = os.path.dirname(path)

        # ── 深色风格对话框 ──
        dlg = QDialog(self)
        dlg.setWindowTitle(f"重命名{'文件夹' if is_dir else '文件'}")
        dlg.setModal(True)
        dlg.setFixedWidth(360)
        dlg.setStyleSheet(f"""
            QDialog {{
                background: {PANEL_COLOR.name()};
                color: {TEXT_PRIMARY.name()};
            }}
            QLabel {{
                color: {TEXT_PRIMARY.name()};
                font-size: 13px;
                font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
                background: transparent;
            }}
            QLineEdit {{
                background: {BG_COLOR.name()};
                color: {TEXT_PRIMARY.name()};
                border: 1px solid #3a3a50;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
                font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
                selection-background-color: {ACCENT_COLOR.name()};
            }}
            QLineEdit:focus {{
                border: 1px solid {ACCENT_COLOR.name()};
            }}
            QPushButton {{
                font-size: 13px;
                font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
                border-radius: 6px;
                padding: 6px 20px;
                min-width: 72px;
            }}
            QPushButton#btn_ok {{
                background: {ACCENT_COLOR.name()};
                color: white;
                border: none;
                font-weight: bold;
            }}
            QPushButton#btn_ok:hover {{ background: {ACCENT2_COLOR.name()}; }}
            QPushButton#btn_cancel {{
                background: #2a2a36;
                color: {TEXT_PRIMARY.name()};
                border: 1px solid #3a3a50;
            }}
            QPushButton#btn_cancel:hover {{ background: #3a3a4a; }}
        """)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        lbl = QLabel(f"{'文件夹' if is_dir else '文件'}名称：")
        layout.addWidget(lbl)

        edit = QLineEdit(old_name)
        layout.addWidget(edit)

        # Windows 风格预选：文件夹全选，文件只选主体（不含扩展名）
        if is_dir:
            edit.selectAll()
        else:
            stem_len = len(Path(old_name).stem)
            edit.setSelection(0, stem_len)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("btn_cancel")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(btn_cancel)

        btn_ok = QPushButton("确定")
        btn_ok.setObjectName("btn_ok")
        btn_ok.setCursor(Qt.PointingHandCursor)
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_ok)

        layout.addLayout(btn_row)

        edit.setFocus()
        edit.returnPressed.connect(dlg.accept)

        if dlg.exec_() != QDialog.Accepted:
            return

        new_name = edit.text().strip()

        # 未改名或为空则跳过
        if not new_name or new_name == old_name:
            return

        # 非法字符检查（Windows 规则，跨平台通用）
        illegal_chars = r'\/:*?"<>|'
        if any(c in new_name for c in illegal_chars):
            QMessageBox.warning(self, "重命名失败",
                f"文件名不能包含以下字符：\n{illegal_chars}")
            return

        new_path = os.path.join(parent_dir, new_name)

        # 目标已存在：询问是否覆盖
        if os.path.exists(new_path):
            reply = QMessageBox.question(
                self, "确认覆盖",
                f"目标位置已存在「{new_name}」，是否替换？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        try:
            os.rename(path, new_path)
            self.status.showMessage(f"已重命名：{old_name}  →  {new_name}")
        except Exception as e:
            QMessageBox.warning(self, "重命名失败", str(e))
            return

        # ── 更新缓存与模型 ──
        if is_dir:
            # 文件夹：迁移缓存和 OrderManager 记录
            self.delegate.invalidate_cache(path)
            self.folder_delegate.invalidate_cache(path)
            # 迁移 OrderManager 记录
            old_norm = normalize_path(os.path.abspath(path))
            new_norm = normalize_path(os.path.abspath(new_path))
            if old_norm in OrderManager._cached_data:
                OrderManager._cached_data[new_norm] = OrderManager._cached_data.pop(old_norm)
                # 保存到配置文件
                save_global_setting("folder_metadata", OrderManager._cached_data)
        else:
            # 媒体文件：删除旧路径缓存
            old_cache_key = f"media:{normalize_path(path)}"
            self.delegate._thumb_cache.pop(old_cache_key, None)
            self.folder_delegate._thumb_cache.pop(old_cache_key, None)
            # 更新父文件夹 OrderManager 中的文件名记录
            om = OrderManager(parent_dir)
            om.remove_image(old_name)
            om.add_image(new_name)

        # 刷新视图
        cur = self.current_path
        self.current_path = None
        self._navigate_to(cur, use_async=False)

    def _on_cut(self, paths: list):
        if not paths:
            return
        self._clipboard_paths = paths
        self._clipboard_is_cut = True
        self.btn_paste.setEnabled(True)
        self.status.showMessage(f"已剪切 {len(paths)} 个文件")

    def _on_copy(self, paths: list):
        if not paths:
            return
        self._clipboard_paths = paths
        self._clipboard_is_cut = False
        self.btn_paste.setEnabled(True)
        self.status.showMessage(f"已复制 {len(paths)} 个文件")

    def _paste_files(self):
        """粘贴剪贴板文件到当前目录"""
        if not self._clipboard_paths:
            self.status.showMessage("剪贴板为空", 2000)
            return
        
        # 目标目录始终是当前路径（无需判断焦点）
        target_dir = self.current_path
        
        if not target_dir:
            self.status.showMessage("请先打开一个文件夹", 2000)
            return
        
        errors = []
        moved_count = 0
        copied_count = 0
        paste_records = []  # 记录所有粘贴操作
        
        # 记录受影响的源文件夹
        affected_source_dirs = set()
        
        # 粘贴前：检查目标文件夹是否为空
        dest_was_empty = self._is_folder_empty_of_media(target_dir)

        for src_path in self._clipboard_paths:
            if not os.path.exists(src_path):
                errors.append(f"{os.path.basename(src_path)}: 源文件不存在")
                continue
            
            filename = os.path.basename(src_path)
            
            # 获取源文件所在目录
            src_dir = os.path.dirname(src_path)
            
            # 判断是否在原地粘贴（复制模式且源目录就是目标目录）
            is_same_dir_copy = (not self._clipboard_is_cut and 
                            os.path.abspath(src_dir) == os.path.abspath(target_dir))
            
            if is_same_dir_copy:
                # 原地复制：自动生成带"copy"后缀的文件名
                base, ext = os.path.splitext(filename)
                counter = 1
                
                # 尝试不同的文件名模式
                # 先尝试 "文件名 - copy.ext"
                dest_path = os.path.join(target_dir, f"{base} - copy{ext}")
                
                # 如果已存在，尝试 "文件名 - copy (2).ext", "文件名 - copy (3).ext" ...
                while os.path.exists(dest_path):
                    counter += 1
                    dest_path = os.path.join(target_dir, f"{base} - copy ({counter}){ext}")
            else:
                # 非原地复制：正常处理
                dest_path = os.path.join(target_dir, filename)
                
                # 避免自己粘贴到自己（剪切模式）
                if self._clipboard_is_cut and os.path.abspath(src_path) == os.path.abspath(dest_path):
                    continue
                
                # 避免覆盖
                if os.path.exists(dest_path):
                    base, ext = os.path.splitext(filename)
                    counter = 1
                    while os.path.exists(dest_path):
                        counter += 1
                        dest_path = os.path.join(target_dir, f"{base} ({counter}){ext}")
            
            try:
                if self._clipboard_is_cut:
                    # 记录源文件夹路径
                    source_dir = os.path.dirname(src_path)
                    affected_source_dirs.add(source_dir)
                    
                    shutil.move(src_path, dest_path)
                    paste_records.append((src_path, dest_path))
                    moved_count += 1
                else:
                    if os.path.isdir(src_path):
                        shutil.copytree(src_path, dest_path)
                    else:
                        shutil.copy2(src_path, dest_path)
                    paste_records.append((src_path, dest_path))
                    copied_count += 1
                    
                    # 原地复制时，将新文件添加到 OrderManager
                    if is_same_dir_copy:
                        om = OrderManager(target_dir)
                        om.add_image(os.path.basename(dest_path))
            except Exception as e:
                errors.append(f"{filename}: {e}")

        # 记录到历史
        if paste_records:
            if self._clipboard_is_cut:
                # 剪切粘贴：记录为移动操作
                self.action_history.push(MoveRecord(paste_records))
            else:
                # 复制粘贴：记录为粘贴操作
                self.action_history.push(PasteRecord(paste_records, is_cut=False))
            self._update_undo_redo_buttons()

        if self._clipboard_is_cut and paste_records:
            # 检查受影响的源文件夹是否为空
            for source_dir in affected_source_dirs:
                if self._is_folder_empty_of_media(source_dir):
                    # 源文件夹现在空了 → 清除缓存
                    self.delegate.invalidate_cache(source_dir)
                    self.folder_delegate.invalidate_cache(source_dir)
                    self.folder_model.refresh_item(source_dir)
                    self._clear_folder_order_records(source_dir)
            
            self._clipboard_paths = []
            self.btn_paste.setEnabled(False)
            self._clipboard_is_cut = False

        # 刷新当前目录
        cur = self.current_path
        self.current_path = None
        self._navigate_to(cur, use_async=False)
        
        # 智能刷新目标文件夹缩略图
        if dest_was_empty and (moved_count > 0 or copied_count > 0):
            # 目标文件夹之前是空的，现在有了文件 → 刷新缩略图
            self.delegate.invalidate_cache(cur)
            self.folder_delegate.invalidate_cache(cur)
            self.folder_model.refresh_item(cur)

        # 显示结果
        if self._clipboard_is_cut:
            op = "移动"
            count = moved_count
        else:
            op = "复制"
            count = copied_count
        
        if errors:
            QMessageBox.warning(self, f"{op}出错", "\n".join(errors))
        elif count > 0:
            self.status.showMessage(f"已{op} {count} 个文件到当前目录")

    def _update_count(self):
        n_imgs = self.file_model.rowCount()
        n_dirs = self.folder_model.rowCount()
        self.lbl_count.setText(f"{n_dirs} 个文件夹  {n_imgs} 个媒体文件")
        
        if self.current_path:
            # 有打开的文件夹：显示面包屑和分栏，隐藏中央标签
            self.central_label_container.setVisible(False)
            self.breadcrumb.setVisible(True)
            self.splitter.setVisible(True)
            
            if n_imgs == 0:
                # 有当前路径但没有媒体文件
                self.left_stacked.setCurrentIndex(1)
                self.empty_label.setText(NO_MEDIA_TEXT)
            else:
                # 有媒体文件
                self.left_stacked.setCurrentIndex(0)
        else:
            # 没有打开文件夹：显示中央标签，隐藏面包屑和分栏
            self.central_label_container.setVisible(True)
            self.breadcrumb.setVisible(False)
            self.splitter.setVisible(False)

# ─────────────────────────────────────────────
#  程序入口
# ─────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PixClass")

    # 开启高DPI适配
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()