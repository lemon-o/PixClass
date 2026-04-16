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
ACCENT2_COLOR  = QColor(154, 117, 234)    # 次强调色
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
        try:
            # 使用 QImageReader 而不是 QImage，以便读取 EXIF 方向
            reader = QImageReader(self.path)
            reader.setAutoTransform(True)  # 关键：自动应用 EXIF 方向变换
            
            img = reader.read()
            if not img.isNull():
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
        try:
            # 尝试提取视频缩略图
            thumbnail = self._extract_thumbnail()
            self.thumbnail_ready.emit(self.path, thumbnail)
        except Exception as e:
            # 如果失败，使用默认占位图
            placeholder = self._make_video_placeholder()
            self.thumbnail_ready.emit(self.path, placeholder)
    
    def _extract_thumbnail(self) -> QPixmap:
        """提取视频缩略图"""
        # 方法1：尝试使用 OpenCV
        try:
            import cv2
            cap = cv2.VideoCapture(self.path)
            if cap.isOpened():
                # 读取第一帧
                ret, frame = cap.read()
                if ret:
                    # 转换颜色空间 BGR -> RGB
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
            pass  # OpenCV 未安装
        
        # 方法2：尝试使用 PyAV
        # try:
        #     import av
        #     container = av.open(self.path)
        #     for frame in container.decode(video=0):
        #         img = frame.to_image()
        #         img = img.convert('RGB')
        #         # 转换为 QImage
        #         data = img.tobytes('raw', 'RGB')
        #         qimage = QImage(data, img.width, img.height, QImage.Format_RGB888)
        #         scaled = qimage.scaled(self.size, self.size,
        #                               Qt.KeepAspectRatio,
        #                               Qt.SmoothTransformation)
        #         return QPixmap.fromImage(scaled)
        except ImportError:
            pass
        
        # 如果无法提取，返回视频占位图
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
            
            # 使用 QImageReader 读取封面，自动应用 EXIF 方向
            reader = QImageReader(self.cover_path)
            reader.setAutoTransform(True)
            img = reader.read()
            
            if img.isNull():
                self.thumbnail_ready.emit(self.folder_path, self.base_px)
                return

            cover_size = int(s * 0.58)
            scaled = img.scaled(cover_size, cover_size,
                                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            cover_px = QPixmap.fromImage(scaled)

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


# ─────────────────────────────────────────────
#  文件/文件夹数据项类
# ─────────────────────────────────────────────
class FileItem:
    def __init__(self, path: str, is_dir: bool):
        self.path = path              # 完整路径
        self.name = os.path.basename(path)  # 文件名/文件夹名
        self.is_dir = is_dir          # 是否为文件夹
        self.thumbnail: Optional[QPixmap] = None  # 缩略图
        self.loading = False          # 是否正在加载缩略图

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
        self.folder_path = os.path.abspath(folder_path)
        if OrderManager._cached_data is None:
            self._load_all()

    def _load_all(self):
        OrderManager._cached_data = load_global_setting("folder_metadata", {})

    def _save_all(self):
        save_global_setting("folder_metadata", OrderManager._cached_data)

    def add_image(self, filename: str):
        """记录图片顺序（用于封面选择）"""
        if self.folder_path not in OrderManager._cached_data:
            OrderManager._cached_data[self.folder_path] = []
        
        if filename not in OrderManager._cached_data[self.folder_path]:
            OrderManager._cached_data[self.folder_path].append(filename)
            self._save_all()

    def get_cover(self) -> Optional[str]:
        """获取封面：先找记录，再找物理文件"""
        folder_data = OrderManager._cached_data.get(self.folder_path, [])
        for name in folder_data:
            full = os.path.join(self.folder_path, name)
            if os.path.exists(full):
                return full
        
        # 兜底逻辑
        try:
            if os.path.exists(self.folder_path):
                files = sorted(os.listdir(self.folder_path))
                for f in files:
                    if Path(f).suffix.lower() in IMAGE_EXTENSIONS:
                        return os.path.join(self.folder_path, f)
        except: pass
        return None

    def remove_image(self, filename: str):
        if self.folder_path in OrderManager._cached_data:
            if filename in OrderManager._cached_data[self.folder_path]:
                OrderManager._cached_data[self.folder_path].remove(filename)
                self._save_all()

# ─────────────────────────────────────────────
#  操作历史：支持撤销 / 重做文件移动
# ─────────────────────────────────────────────
class MoveRecord:
    """记录一次批量移动操作（支持整批撤销 / 重做）"""
    def __init__(self, moves: list[tuple[str, str]]):
        # moves: [(src_path, dst_path), ...]  dst_path 为移动后的实际完整路径
        self.moves = moves


class ActionHistory:
    """轻量撤销/重做栈，只跟踪文件移动操作"""
    MAX_DEPTH = 50  # 最多保留 50 步历史

    def __init__(self):
        self._undo_stack: list[MoveRecord] = []
        self._redo_stack: list[MoveRecord] = []

    def push(self, record: MoveRecord):
        """记录一步操作，清空 redo 栈"""
        self._undo_stack.append(record)
        if len(self._undo_stack) > self.MAX_DEPTH:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def pop_undo(self) -> Optional[MoveRecord]:
        if self._undo_stack:
            rec = self._undo_stack.pop()
            self._redo_stack.append(rec)
            return rec
        return None

    def pop_redo(self) -> Optional[MoveRecord]:
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
class FileListModel(QAbstractListModel):
    ITEM_ROLE = Qt.UserRole + 1  # 自定义数据角色

    def __init__(self):
        super().__init__()
        self.items: list[FileItem] = []  # 数据项列表

    def rowCount(self, parent=QModelIndex()):
        # 返回列表项数量
        return len(self.items)

    def data(self, index, role=Qt.DisplayRole):
        # 获取指定索引的数据
        if not index.isValid() or index.row() >= len(self.items):
            return QVariant()
        item = self.items[index.row()]
        if role == Qt.DisplayRole:
            return item.name
        if role == self.ITEM_ROLE:
            return item
        return QVariant()

    def flags(self, index):
        # 设置项的交互属性
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.isValid():
            item = self.items[index.row()]
            if item.is_image():
                base |= Qt.ItemIsDragEnabled  # 图片可拖拽
            if item.is_dir:
                base |= Qt.ItemIsDropEnabled  # 文件夹可接收拖拽
        return base

    def supportedDropActions(self):
        # 支持移动操作
        return Qt.MoveAction

    def mimeTypes(self):
        # 自定义拖拽数据类型
        return ['application/x-imgclassifier-items']

    def mimeData(self, indexes):
        # 生成拖拽数据
        paths = []
        for idx in indexes:
            item = self.items[idx.row()]
            if item.is_image():
                paths.append(item.path)
        mime = QMimeData()
        mime.setData('application/x-imgclassifier-items',
                     '\n'.join(paths).encode('utf-8'))
        return mime

    def load_folder(self, folder_path: str, dirs_only: bool = False, files_only: bool = False):
        # 加载文件夹内容到模型（dirs_only=True 只加目录，files_only=True 只加文件）
        self.beginResetModel()
        self.items.clear()
        
        try:
            with os.scandir(folder_path) as it:
                dirs = []
                images = []
                
                for entry in it:
                    # 过滤隐藏文件和配置文件
                    if entry.name.startswith('.') or entry.name.startswith('_imgclass'):
                        continue
                        
                    try:
                        if entry.is_dir():
                            if not files_only:
                                dirs.append(FileItem(entry.path, True))
                        else:
                            if not dirs_only:
                                ext = Path(entry.name).suffix.lower()
                                if ext in ALL_MEDIA_EXTENSIONS:
                                    images.append(FileItem(entry.path, False))
                    except OSError:
                        continue
        except (PermissionError, FileNotFoundError):
            self.endResetModel()
            return

        # 排序
        dirs.sort(key=lambda x: x.name.lower())
        images.sort(key=lambda x: x.name.lower())
        
        self.items = dirs + images
        self.endResetModel()

    def get_item(self, index: QModelIndex) -> Optional[FileItem]:
        # 根据索引获取数据项
        if index.isValid() and 0 <= index.row() < len(self.items):
            return self.items[index.row()]
        return None

    def refresh_item(self, path: str):
        # 刷新指定路径的项
        for i, item in enumerate(self.items):
            if item.path == path:
                item.thumbnail = None
                idx = self.index(i)
                self.dataChanged.emit(idx, idx)
                break

    def remove_item(self, path: str):
        # 移除指定路径的项
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
        self._placeholder_folder = self._make_folder_icon()    # 文件夹默认图标
        self._placeholder_image = self._make_image_placeholder()# 图片默认占位图

        # 定期清理已结束的线程（避免在 paint() 中清理，减少每帧开销）
        self._cleanup_timer = QTimer()
        self._cleanup_timer.setInterval(2000)
        self._cleanup_timer.timeout.connect(self._cleanup_loaders)
        self._cleanup_timer.start()

    def _cleanup_loaders(self):
        self._loaders = [l for l in self._loaders if l.isRunning()]

    def set_drop_target(self, path: Optional[str]):
        # 设置拖拽高亮目标
        self._drop_target = path

    def set_thumb_size(self, size: int):
        # 设置缩略图尺寸，清空缓存
        self.thumb_size = size
        self._thumb_cache.clear()
        self._loading_folders.clear()
        self._placeholder_folder = self._make_folder_icon()
        self._placeholder_image = self._make_image_placeholder()

    def invalidate_cache(self, path: str):
        # 失效指定路径的缓存（包含 folder: 和 cover: 前缀的 key）
        keys = [k for k in self._thumb_cache if path in k]
        for k in keys:
            del self._thumb_cache[k]
        self._loading_folders.discard(path)

    def _make_folder_icon(self) -> QPixmap:
        # 绘制文件夹默认图标
        s = self.thumb_size
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

    def _make_image_placeholder(self) -> QPixmap:
        # 绘制图片默认占位图
        s = self.thumb_size
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

    def _build_folder_thumbnail(self, item: FileItem, index: QModelIndex) -> QPixmap:
        """获取文件夹缩略图（异步加载封面，首次返回占位图）"""
        cache_key = f"folder:{item.path}:{self.thumb_size}"
        if cache_key in self._thumb_cache:
            return self._thumb_cache[cache_key]

        # 已在加载中，直接返回基底占位图
        if item.path in self._loading_folders:
            return self._placeholder_folder

        base = self._placeholder_folder.copy()
        om = OrderManager(item.path)
        cover_path = om.get_cover()

        if not cover_path:
            # 无封面，直接缓存并返回
            self._thumb_cache[cache_key] = base
            return base

        # 启动后台线程异步加载封面
        item.loading = True
        self._loading_folders.add(item.path)
        loader = FolderThumbnailLoader(item.path, cover_path, self.thumb_size, base)

        def on_folder_ready(folder_path, px):
            self._thumb_cache[f"folder:{folder_path}:{self.thumb_size}"] = px
            self._loading_folders.discard(folder_path)
            # 找到该文件夹对应的 item，清除 loading 标志并通知刷新
            for i, it in enumerate(self.model.items):
                if it.path == folder_path:
                    it.loading = False
                    idx = self.model.index(i)
                    self.model.dataChanged.emit(idx, idx)
                    break

        loader.thumbnail_ready.connect(on_folder_ready)
        loader.start()
        self._loaders.append(loader)

        return base

    def _get_media_thumbnail(self, item: FileItem, index: QModelIndex) -> QPixmap:
        """获取媒体文件缩略图（图片或视频）"""
        cache_key = f"media:{item.path}:{self.thumb_size}"
        if cache_key in self._thumb_cache:
            return self._thumb_cache[cache_key]

        if not item.loading:
            item.loading = True
            
            if item.is_video():
                loader = VideoThumbnailLoader(item.path, self.thumb_size)
            else:
                loader = ThumbnailLoader(item.path, self.thumb_size)

            def on_ready(path, px):
                self._thumb_cache[f"media:{path}:{self.thumb_size}"] = px
                item.loading = False
                if index.isValid():
                    model = index.model()
                    if model:
                        model.dataChanged.emit(index, index)

            loader.thumbnail_ready.connect(on_ready)
            loader.start()
            self._loaders.append(loader)
            # 线程清理由 _cleanup_timer 统一处理，不在此处执行

        return self._placeholder_image

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

        # 拖拽指示箭头
        # if is_hovered:
        #     arrow_size = 24
        #     ax = card_rect.center().x() - arrow_size // 2
        #     ay = card_rect.center().y() - arrow_size // 2
        #     painter.setPen(QPen(DROP_BORDER, 2))
        #     painter.setBrush(QBrush(QColor(99, 179, 237, 200)))
        #     painter.drawEllipse(ax, ay, arrow_size, arrow_size)
        #     painter.setPen(QPen(Qt.white, 2))
        #     # 向下箭头
        #     cx2 = ax + arrow_size // 2
        #     painter.drawLine(cx2, ay + 5, cx2, ay + arrow_size - 7)
        #     pts = [QPoint(cx2 - 5, ay + arrow_size - 10),
        #            QPoint(cx2, ay + arrow_size - 5),
        #            QPoint(cx2 + 5, ay + arrow_size - 10)]
        #     for i in range(len(pts) - 1):
        #         painter.drawLine(pts[i], pts[i + 1])

        painter.restore()


# ─────────────────────────────────────────────
#  图片网格视图：自定义拖拽和双击逻辑
# ─────────────────────────────────────────────
class ImageGridView(QListView):
    folder_entered = pyqtSignal(str)          # 进入文件夹信号
    image_opened = pyqtSignal(str)            # 打开图片信号
    items_moved = pyqtSignal(list, str)       # 图片移动信号(路径列表,目标文件夹)

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
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar:horizontal {{
                background: {PANEL_COLOR.name()};
                height: 8px;
            }}
            QScrollBar::handle:horizontal {{
                background: #555566;
                border-radius: 4px;
            }}
        """)

    def update_thumb_size(self, size: int):
        # 更新缩略图尺寸
        self.file_delegate.set_thumb_size(size)
        cell = size + 40
        self.setGridSize(QSize(cell, cell))
        self.scheduleDelayedItemsLayout()

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

    def mousePressEvent(self, event):
        # 记录拖拽起始位置
        if event.button() == Qt.LeftButton:
            self._drag_start = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # 处理拖拽操作
        if (event.buttons() & Qt.LeftButton and
                self._drag_start and
                (event.pos() - self._drag_start).manhattanLength() > 10):

            selected = self.selectedIndexes()
            drag_items = []
            for idx in selected:
                item: FileItem = idx.data(FileListModel.ITEM_ROLE)
                if item and item.is_image():
                    drag_items.append(item)

            if drag_items:
                # ==============================================
                # 【修复】先创建拖拽对象 → 强制设置 mimeData
                # ==============================================
                drag = QDrag(self)
                
                # 强制生成拖拽数据（必须在 exec_ 之前设置）
                paths = [i.path for i in drag_items]
                mime = QMimeData()
                mime.setData('application/x-imgclassifier-items',
                            '\n'.join(paths).encode('utf-8'))
                drag.setMimeData(mime)  # 关键修复：确保设置 mimeData

                # 拖拽图标：第一张图片缩略图
                first = drag_items[0]
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
        self.current_path: Optional[str] = None  # 当前路径
        self.root_path: Optional[str] = None     # 根路径
        self.history: list[str] = []             # 浏览历史
        self.action_history = ActionHistory()    # 文件移动撤销/重做历史

        # 滑块防抖定时器（300ms 后才真正更新缩略图大小）
        self._thumb_size_timer = QTimer()
        self._thumb_size_timer.setSingleShot(True)
        self._thumb_size_timer.setInterval(300)
        self._thumb_size_timer.timeout.connect(self._apply_thumb_size)

        self.setWindowTitle("PixClass")
        self.setMinimumSize(900, 620)
        # 启动时窗口最大化
        self.showMaximized()
        self._setup_ui()
        self._apply_global_style()

        QTimer.singleShot(100, self._load_last_session)

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
        self.slider.setToolTip("调整缩略图大小")
        self.slider.valueChanged.connect(self._on_thumb_size_changed)
        toolbar.addWidget(self.slider)

        toolbar.addSeparator()

        # 数量统计标签
        self.lbl_count = QLabel("0 项")
        self.lbl_count.setStyleSheet(f"color: {TEXT_SECONDARY.name()}; font-size: 12px; padding: 0 8px;")
        toolbar.addWidget(self.lbl_count)

        # ── 导航栏 ──
        self.breadcrumb = BreadcrumbBar()
        self.breadcrumb.path_selected.connect(self._navigate_to)
        self.breadcrumb.setFixedHeight(36)
        main_layout.addWidget(self.breadcrumb)

        # ── 左右分栏容器 ──
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background: #2a2a36;
                width: 2px;
            }}
        """)
        main_layout.addWidget(splitter, 1)

        # ── 左侧：图片网格 ──
        left_widget = QWidget()
        left_widget.setStyleSheet(f"background: {BG_COLOR.name()};")
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self.file_model = FileListModel()
        self.delegate = FileItemDelegate(self.file_model, DEFAULT_THUMB_SIZE)
        self.grid_view = ImageGridView(self.file_model, self.delegate)
        cell = DEFAULT_THUMB_SIZE + 40
        self.grid_view.setGridSize(QSize(cell, cell))
        self.grid_view.folder_entered.connect(self._navigate_to)
        self.grid_view.image_opened.connect(self._open_image)
        self.grid_view.items_moved.connect(self._on_items_moved)
        self.file_model.rowsInserted.connect(self._update_count)
        self.file_model.rowsRemoved.connect(self._update_count)
        self.file_model.modelReset.connect(self._update_count)
        left_layout.addWidget(self.grid_view, 1)

        # ── 空状态提示（放在左侧） ──
        self.empty_label = QLabel(
            "📂\n\n点击「打开文件夹」选择图片目录\n\n"
            "支持 JPG / PNG / GIF / BMP / WebP"
        )
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(f"""
            color: {TEXT_SECONDARY.name()};
            font-size: 15px;
            font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
            line-height: 2;
            background: {BG_COLOR.name()};
        """)
        left_layout.addWidget(self.empty_label)

        splitter.addWidget(left_widget)

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
        folder_cell = DEFAULT_THUMB_SIZE + 40
        self.folder_view.setGridSize(QSize(folder_cell, folder_cell))
        self.folder_view.folder_entered.connect(self._navigate_to)
        self.folder_view.image_opened.connect(self._open_image)
        # 拖拽图片到右侧文件夹时也触发 items_moved
        self.folder_view.items_moved.connect(self._on_items_moved)
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
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        right_layout.addWidget(self.folder_view, 1)

        # 右侧空提示（无子文件夹时）
        self.folder_empty_label = QLabel("暂无子文件夹\n\n点击 ＋ 新建文件夹")
        self.folder_empty_label.setAlignment(Qt.AlignCenter)
        self.folder_empty_label.setStyleSheet(f"""
            color: {TEXT_SECONDARY.name()};
            font-size: 13px;
            font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
            background: transparent;
            line-height: 2;
        """)
        right_layout.addWidget(self.folder_empty_label)

        splitter.addWidget(right_widget)

        # 初始比例：
        splitter.setSizes([700, 920])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        # 初始状态隐藏右侧内容
        self.folder_view.setVisible(False)
        self.folder_empty_label.setVisible(False)

        # 状态栏
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("就绪 — 请打开一个文件夹以开始分类")

    def _load_last_session(self):
            """启动时加载上次访问的目录"""
            last_path = load_global_setting("last_root_path")
            if last_path and os.path.exists(last_path):
                self.root_path = last_path
                self._navigate_to(last_path)
                self.status.showMessage(f"已恢复上次会话: {last_path}")

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
            self._navigate_to(folder)

    def _navigate_to(self, path: str):
        """导航到指定路径，左侧显示图片，右侧显示子文件夹"""
        if not os.path.exists(path):
            return

        if self.current_path and path != self.current_path:
            self.history.append(self.current_path)
            self.btn_hist_back.setEnabled(True)

        self.current_path = path

        # ── 左侧：加载图片（load_folder 内已含 beginResetModel/endResetModel）──
        self.file_model.load_folder(path, dirs_only=False, files_only=True)

        self.breadcrumb.set_path(path, self.root_path or path)

        can_go_up = self.root_path and path != self.root_path
        self.btn_back.setEnabled(bool(can_go_up))

        # ── 右侧：加载子文件夹 ──
        self.folder_model.load_folder(path, dirs_only=True, files_only=False)

        has_folders = self.folder_model.rowCount() > 0
        self.folder_view.setVisible(has_folders)
        self.folder_empty_label.setVisible(not has_folders)
        self.btn_create_folder.setEnabled(True)

        self.grid_view.setVisible(True)
        self.empty_label.setVisible(False)

        self.status.showMessage(f"当前目录: {path}")
        self._update_count()
        self._update_undo_redo_buttons()

        if self.root_path:
            save_global_setting("last_root_path", self.root_path)

    def _go_up(self):
        if self.current_path and self.root_path:
            parent = os.path.dirname(self.current_path)
            if parent != self.current_path:
                self._navigate_to(parent)

    def _go_history_back(self):
        if self.history:
            prev = self.history.pop()
            self.current_path = None
            self._navigate_to(prev)
            if not self.history:
                self.btn_hist_back.setEnabled(False)

    def _refresh(self):
        """刷新当前目录（同时更新左侧图片和右侧文件夹缩略图）"""
        if self.current_path:
            # 清除当前目录缓存
            self.delegate.invalidate_cache(self.current_path)
            self.folder_delegate.invalidate_cache(self.current_path)
            # 清除所有子文件夹的封面缓存
            try:
                with os.scandir(self.current_path) as it:
                    for entry in it:
                        if entry.is_dir():
                            self.delegate.invalidate_cache(entry.path)
                            self.folder_delegate.invalidate_cache(entry.path)
            except Exception:
                pass
            cur = self.current_path
            self.current_path = None
            self._navigate_to(cur)
            self.status.showMessage("已刷新")

    def _create_folder(self):
        if not self.current_path:
            return
        name, ok = QInputDialog.getText(self, "新建文件夹", "文件夹名称:")
        if ok and name.strip():
            new_path = os.path.join(self.current_path, name.strip())
            try:
                os.makedirs(new_path, exist_ok=True)
                cur = self.current_path
                self.current_path = None
                self._navigate_to(cur)
                self.status.showMessage(f"已创建文件夹: {name.strip()}")
            except Exception as e:
                QMessageBox.warning(self, "创建失败", str(e))

    def _on_thumb_size_changed(self, value: int):
        # 仅重启防抖定时器，不立即更新（避免拖动时每帧都重建缓存）
        self._pending_thumb_size = value
        self._thumb_size_timer.start()

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
        """处理图片拖拽移动，移动后立即刷新目标文件夹缩略图"""
        order_mgr = OrderManager(dest_folder)
        moved_count = 0
        errors = []
        move_records: list[tuple[str, str]] = []  # (src, dst) 成功移动的记录

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
                self.file_model.remove_item(src_path)
                move_records.append((src_path, dest_path))
                moved_count += 1
            except Exception as e:
                errors.append(f"{filename}: {e}")

        # 记录历史（只记录成功的）
        if move_records:
            self.action_history.push(MoveRecord(move_records))
            self._update_undo_redo_buttons()

        # 彻底清除目标文件夹的缩略图缓存
        self.delegate.invalidate_cache(dest_folder)
        self.folder_delegate.invalidate_cache(dest_folder)

        # 刷新右侧对应文件夹项的缩略图
        self.folder_model.refresh_item(dest_folder)
        self.folder_view.viewport().update()
        self.grid_view.viewport().update()

        if errors:
            QMessageBox.warning(self, "移动出错",
                                "以下文件移动失败:\n" + "\n".join(errors))

        self.status.showMessage(f"已将 {moved_count} 张图片移入 「{os.path.basename(dest_folder)}」")

    def _undo_move(self):
        """撤销上一步文件移动"""
        if not self.action_history.can_undo():
            return
        rec = self.action_history.pop_undo()
        if not rec:
            return

        errors = []
        affected_src_dirs: set[str] = set()
        affected_dst_dirs: set[str] = set()

        # 逆序还原：把 dst 移回 src
        for src_path, dst_path in reversed(rec.moves):
            if not os.path.exists(dst_path):
                errors.append(f"{os.path.basename(dst_path)}: 文件不存在")
                continue
            # 确保原目录仍然存在
            src_dir = os.path.dirname(src_path)
            if not os.path.exists(src_dir):
                errors.append(f"{os.path.basename(src_path)}: 原文件夹不存在")
                continue
            # 处理回移冲突
            restore_path = src_path
            if os.path.exists(restore_path) and restore_path != dst_path:
                base, ext = os.path.splitext(os.path.basename(src_path))
                counter = 1
                while os.path.exists(restore_path):
                    restore_path = os.path.join(src_dir, f"{base}_{counter}{ext}")
                    counter += 1
            try:
                shutil.move(dst_path, restore_path)
                affected_dst_dirs.add(os.path.dirname(dst_path))
                affected_src_dirs.add(src_dir)
            except Exception as e:
                errors.append(f"{os.path.basename(dst_path)}: {e}")

        self._refresh_after_undo_redo(affected_src_dirs | affected_dst_dirs)
        self._update_undo_redo_buttons()

        if errors:
            QMessageBox.warning(self, "撤销出错", "\n".join(errors))
        else:
            n = len(rec.moves)
            self.status.showMessage(f"已撤销：还原了 {n} 张图片")

    def _redo_move(self):
        """重做下一步文件移动"""
        if not self.action_history.can_redo():
            return
        rec = self.action_history.pop_redo()
        if not rec:
            return

        errors = []
        affected_dirs: set[str] = set()

        for src_path, dst_path in rec.moves:
            # redo 时 src 已经在还原位置
            restore_path = src_path  # 撤销后文件在原位，可能有重命名，此处尝试原路径
            if not os.path.exists(restore_path):
                errors.append(f"{os.path.basename(src_path)}: 文件不存在，无法重做")
                continue
            dest_folder = os.path.dirname(dst_path)
            if not os.path.exists(dest_folder):
                errors.append(f"目标文件夹不存在: {dest_folder}")
                continue
            redo_dst = dst_path
            if os.path.exists(redo_dst) and redo_dst != restore_path:
                base, ext = os.path.splitext(os.path.basename(dst_path))
                counter = 1
                while os.path.exists(redo_dst):
                    redo_dst = os.path.join(dest_folder, f"{base}_{counter}{ext}")
                    counter += 1
            try:
                shutil.move(restore_path, redo_dst)
                affected_dirs.add(os.path.dirname(restore_path))
                affected_dirs.add(dest_folder)
            except Exception as e:
                errors.append(f"{os.path.basename(restore_path)}: {e}")

        self._refresh_after_undo_redo(affected_dirs)
        self._update_undo_redo_buttons()

        if errors:
            QMessageBox.warning(self, "重做出错", "\n".join(errors))
        else:
            n = len(rec.moves)
            self.status.showMessage(f"已重做：移动了 {n} 张图片")

    def _refresh_after_undo_redo(self, affected_dirs: set[str]):
        """撤销/重做后刷新受影响的目录缓存，并重新加载当前视图"""
        for d in affected_dirs:
            self.delegate.invalidate_cache(d)
            self.folder_delegate.invalidate_cache(d)
            self.folder_model.refresh_item(d)
        # 重新加载当前目录
        if self.current_path:
            cur = self.current_path
            self.current_path = None
            self._navigate_to(cur)

    def _update_undo_redo_buttons(self):
        self.btn_undo.setEnabled(self.action_history.can_undo())
        self.btn_redo.setEnabled(self.action_history.can_redo())

    def _update_count(self):
        n_imgs = self.file_model.rowCount()
        n_dirs = self.folder_model.rowCount()
        self.lbl_count.setText(f"{n_dirs} 个文件夹  {n_imgs} 张图片")


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