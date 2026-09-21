import sys
import os
import traceback
import time
import subprocess
from PIL import Image

# Thử import các thư viện hỗ trợ JXL
try:
    import pillow_jxl
    import imagecodecs
    JXL_SUPPORTED = True
    JXL_ERROR = ""
except Exception as e:
    JXL_SUPPORTED = False
    JXL_ERROR = traceback.format_exc()

# Thử import OpenCV cho Tab 3
try:
    import cv2
    OPENCV_AVAILABLE = True
except Exception as e:
    OPENCV_AVAILABLE = False

from PySide6.QtCore import Qt, QThread, Signal, QSize, QCoreApplication, QRect, QTimer, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QSlider, QRadioButton, QButtonGroup,
    QGroupBox, QMessageBox, QFrame, QComboBox, QTabWidget, QLineEdit,
    QTextBrowser, QScrollArea
)
from PySide6.QtGui import (
    QDragEnterEvent, QDropEvent, QIcon, QColor, QFont,
    QImage, QPixmap, QPainter, QPen, QBrush
)

import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed


def convert_single_media(args):
    file_path, output_dir_mode, custom_output_dir, target_format, quality, video_crf, prefix, suffix = args
    try:
        import subprocess
        # Bảo đảm đăng ký JXL trong tiến trình con (nếu file đầu vào là JXL)
        import pillow_jxl
        from PIL import Image
        
        # Danh sách định dạng hỗ trợ
        img_exts = (".jxl", ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff")
        vid_exts = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv")
        
        in_ext = os.path.splitext(file_path)[1].lower()
        is_input_video = in_ext in vid_exts
        is_input_image = in_ext in img_exts
        
        fmt_lower = target_format.lower()
        is_target_video = fmt_lower in ("mp4", "webm", "mkv", "avi")
        is_target_audio = fmt_lower == "mp3"
        is_target_image = fmt_lower in ("jpeg", "jpg", "png", "webp", "bmp", "tiff")
        
        # Xác định thư mục lưu file đầu ra
        if output_dir_mode == "same":
            out_dir = os.path.dirname(file_path)
        else:
            out_dir = custom_output_dir
            
        # Áp dụng tiền tố và hậu tố vào tên file đầu ra
        orig_base_name = os.path.splitext(os.path.basename(file_path))[0]
        base_name = f"{prefix}{orig_base_name}{suffix}"
        
        ext = "jpg" if fmt_lower == "jpeg" else fmt_lower
        out_path = os.path.join(out_dir, f"{base_name}.{ext}")
        
        # Xác định đường dẫn ffmpeg.exe trong dự án
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        ffmpeg_path = os.path.join(base_dir, "ffmpeg", "ffmpeg.exe")
        
        # --- TRƯỜNG HỢP 1: ĐẦU RA LÀ VIDEO HOẶC AUDIO (Cần dùng FFmpeg) ---
        if is_target_video or is_target_audio:
            if not os.path.exists(ffmpeg_path):
                return file_path, "Lỗi", "Thiếu ffmpeg.exe tại ffmpeg/"
                
            if is_input_image:
                return file_path, "Lỗi", "Không hỗ trợ chuyển đổi ảnh sang video/audio"
                
            # Thiết lập lệnh FFmpeg tương ứng
            if is_target_audio:
                # Tách nhạc sang MP3 chất lượng cao
                cmd = [ffmpeg_path, "-y", "-i", file_path, "-vn", "-c:a", "libmp3lame", "-q:a", "2", out_path]
            else:
                # Chuyển đổi định dạng video áp dụng mức nén video_crf
                if fmt_lower == "mp4":
                    cmd = [ffmpeg_path, "-y", "-i", file_path, "-c:v", "libx264", "-crf", str(video_crf), "-pix_fmt", "yuv420p", out_path]
                elif fmt_lower == "mkv":
                    cmd = [ffmpeg_path, "-y", "-i", file_path, "-c:v", "libx264", "-crf", str(video_crf), out_path]
                elif fmt_lower == "webm":
                    # WebM (sử dụng VP8 với -crf và đặt bitrate video -b:v 0 để kích hoạt constant quality)
                    cmd = [ffmpeg_path, "-y", "-i", file_path, "-c:v", "libvpx", "-crf", str(video_crf), "-b:v", "0", out_path]
                else: # AVI
                    # Xvid sử dụng -qscale:v (CRF 18 tương đương qscale 3, 23 tương đương 5, 28 tương đương 7)
                    qscale = 3 if video_crf == 18 else (5 if video_crf == 23 else 7)
                    cmd = [ffmpeg_path, "-y", "-i", file_path, "-c:v", "libxvid", "-qscale:v", str(qscale), out_path]
            
            # Cấu hình để ẩn cửa sổ dòng lệnh màu đen trên Windows
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            if res.returncode != 0:
                err_msg = res.stderr.decode('utf-8', errors='ignore')
                return file_path, "Lỗi", f"FFmpeg (Code {res.returncode}): {err_msg[:80]}"
                
            # Kiểm tra xem tệp tin đầu ra có thực sự tồn tại và có dung lượng lớn hơn 0 không
            if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
                return file_path, "Lỗi", f"FFmpeg bao thanh cong nhung khong thay tep: {os.path.basename(out_path)}"
                
            return file_path, "Thành công", f"Đã lưu: {os.path.basename(out_path)}"
            
        # --- TRƯỜNG HỢP 2: ĐẦU RA LÀ ẢNH (Tương thích cả đầu vào ảnh và video) ---
        elif is_target_image:
            if is_input_video:
                # Trích xuất khung hình đầu tiên của video làm ảnh đại diện
                if not os.path.exists(ffmpeg_path):
                    return file_path, "Lỗi", "Thiếu ffmpeg.exe để trích xuất ảnh"
                    
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    
                cmd = [ffmpeg_path, "-y", "-i", file_path, "-vframes", "1", out_path]
                res = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    startupinfo=startupinfo,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                
                if res.returncode != 0:
                    err_msg = res.stderr.decode('utf-8', errors='ignore')
                    return file_path, "Lỗi", f"FFmpeg (Code {res.returncode}): {err_msg[:80]}"
                    
                # Kiểm tra xem tệp tin đầu ra có thực sự tồn tại và có dung lượng lớn hơn 0 không
                if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
                    return file_path, "Lỗi", f"FFmpeg bao thanh cong nhung khong thay anh: {os.path.basename(out_path)}"
                    
                return file_path, "Thành công", f"Đã trích xuất khung hình: {os.path.basename(out_path)}"
            
            else:
                # Chuyển đổi ảnh sang ảnh qua Pillow
                with Image.open(file_path) as img:
                    if fmt_lower in ("jpeg", "jpg"):
                        # JPEG không hỗ trợ trong suốt, cần lót nền trắng nếu có kênh Alpha
                        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                            background = Image.new("RGB", img.size, (255, 255, 255))
                            rgba_img = img.convert("RGBA")
                            background.paste(rgba_img, mask=rgba_img.split()[3])
                            background.save(out_path, "JPEG", quality=quality)
                        else:
                            rgb_img = img.convert("RGB")
                            rgb_img.save(out_path, "JPEG", quality=quality)
                            
                    elif fmt_lower == "webp":
                        img.save(out_path, "WEBP", quality=quality)
                        
                    elif fmt_lower == "png":
                        img.save(out_path, "PNG")
                        
                    elif fmt_lower == "bmp":
                        rgb_img = img.convert("RGB")
                        rgb_img.save(out_path, "BMP")
                        
                    elif fmt_lower == "tiff":
                        img.save(out_path, "TIFF")
                    else:
                        img.save(out_path, target_format.upper())

                # Kiểm tra lại trên đĩa
                if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
                    return file_path, "Lỗi", f"Lỗi Pillow khong tao duoc file: {os.path.basename(out_path)}"

                return file_path, "Thành công", f"Đã lưu: {os.path.basename(out_path)}"

        return file_path, "Lỗi", "Không xác định loại chuyển đổi"
    except Exception as e:
        return file_path, "Lỗi", str(e)


class ConversionWorker(QThread):
    file_processed = Signal(str, str, str)  # path, status, message
    overall_progress = Signal(int)  # current converted count
    finished = Signal()

    def __init__(self, files, output_dir_mode, custom_output_dir, target_format, quality, video_crf=23, prefix="", suffix=""):
        super().__init__()
        self.files = files
        self.output_dir_mode = output_dir_mode
        self.custom_output_dir = custom_output_dir
        self.target_format = target_format
        self.quality = quality
        self.video_crf = video_crf
        self.prefix = prefix
        self.suffix = suffix
        self.is_running = True
        self._executor = None

    def stop(self):
        self.is_running = False
        if self._executor:
            try:
                self._executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

    def run(self):
        num_workers = max(1, multiprocessing.cpu_count() - 1)
        
        tasks = [
            (file_path, self.output_dir_mode, self.custom_output_dir, self.target_format, self.quality, self.video_crf, self.prefix, self.suffix)
            for file_path in self.files
        ]
        
        converted_count = 0
        self._executor = ProcessPoolExecutor(max_workers=num_workers)
        
        try:
            futures = {
                self._executor.submit(convert_single_media, task): task[0]
                for task in tasks
            }
            
            for future in as_completed(futures):
                if not self.is_running:
                    try:
                        self._executor.shutdown(wait=False, cancel_futures=True)
                    except Exception:
                        pass
                    break
                
                try:
                    file_path, status, message = future.result()
                    self.file_processed.emit(file_path, status, message)
                except Exception as e:
                    bad_file = futures[future]
                    self.file_processed.emit(bad_file, "Lỗi", f"Tiến trình bị sập: {str(e)}")
                
                converted_count += 1
                self.overall_progress.emit(converted_count)
                time.sleep(0.001)
                
        finally:
            try:
                self._executor.shutdown(wait=True)
            except Exception:
                pass
            self._executor = None
            
        self.finished.emit()


class VideoEditWorker(QThread):
    finished = Signal(bool, str)

    def __init__(self, ffmpeg_path, input_path, out_path, start_time, end_time, crop_rect, video_width, video_height):
        super().__init__()
        self.ffmpeg_path = ffmpeg_path
        self.input_path = input_path
        self.out_path = out_path
        self.start_time = start_time
        self.end_time = end_time
        self.crop_rect = crop_rect  # (x, y, w, h)
        self.video_width = video_width
        self.video_height = video_height

    def run(self):
        try:
            x, y, w, h = self.crop_rect
            
            # Cắt ngắn và cắt khung bằng FFmpeg
            # Vì cần đổi kích thước pixel (crop), bắt buộc phải re-encode video (-c:v libx264).
            cmd = [
                self.ffmpeg_path, "-y",
                "-ss", f"{self.start_time:.3f}",
                "-to", f"{self.end_time:.3f}",
                "-i", self.input_path,
                "-filter:v", f"crop={w}:{h}:{x}:{y}",
                "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                self.out_path
            ]
            
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            if res.returncode == 0 and os.path.exists(self.out_path) and os.path.getsize(self.out_path) > 0:
                self.finished.emit(True, f"Đã lưu: {os.path.basename(self.out_path)}")
            else:
                err = res.stderr.decode('utf-8', errors='ignore')
                self.finished.emit(False, f"FFmpeg (Code {res.returncode}): {err[:150]}")
        except Exception as e:
            self.finished.emit(False, str(e))


class DropZone(QLabel):
    filesDropped = Signal(list)

    def __init__(self, mode="image"):
        super().__init__()
        self.mode = mode
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self.mode == "image":
            self.setText("Kéo & thả các tệp tin ảnh hoặc thư mục vào đây\n(Hỗ trợ: JXL, JPG, PNG, WebP, BMP, TIFF)\n\n(Hoặc click đúp để chọn từ máy tính)")
        else:
            self.setText("Kéo & thả một tệp tin video vào đây để chỉnh sửa\n(Hỗ trợ: MP4, MKV, AVI, MOV, WebM, FLV, WMV)\n\n(Hoặc click đúp để chọn từ máy tính)")
        self.setWordWrap(True)
        self.setMinimumHeight(120)
        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #a0a0a0;
                border-radius: 10px;
                background-color: #fdfdfd;
                color: #555555;
                font-size: 14px;
                font-weight: bold;
                padding: 15px;
            }
        """)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            self.setStyleSheet("""
                QLabel {
                    border: 2px dashed #0078d4;
                    border-radius: 10px;
                    background-color: #eff6fc;
                    color: #0078d4;
                    font-size: 14px;
                    font-weight: bold;
                    padding: 15px;
                }
            """)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #a0a0a0;
                border-radius: 10px;
                background-color: #fdfdfd;
                color: #555555;
                font-size: 14px;
                font-weight: bold;
                padding: 15px;
            }
        """)

    def dropEvent(self, event):
        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #a0a0a0;
                border-radius: 10px;
                background-color: #fdfdfd;
                color: #555555;
                font-size: 14px;
                font-weight: bold;
                padding: 15px;
            }
        """)
        urls = event.mimeData().urls()
        paths = [url.toLocalFile() for url in urls if url.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.filesDropped.emit(["__SELECT_FILES__"])


class QRangeSlider(QWidget):
    rangeChanged = Signal(int, int)
    sliderPressed = Signal()
    sliderReleased = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.min_val = 0
        self.max_val = 100
        self.start_val = 0
        self.end_val = 100
        
        self.active_handle = None
        self.handle_width = 16
        self.handle_height = 20
        self.setMinimumHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def setRange(self, min_val, max_val):
        self.min_val = min_val
        self.max_val = max_val
        self.start_val = max(self.min_val, min(self.start_val, self.max_val))
        self.end_val = max(self.start_val, min(self.end_val, self.max_val))
        self.update()

    def setValues(self, start_val, end_val):
        self.start_val = max(self.min_val, min(start_val, self.max_val))
        self.end_val = max(self.start_val, min(end_val, self.max_val))
        self.update()

    def getValues(self):
        return self.start_val, self.end_val

    def value_to_pos(self, val):
        if self.max_val == self.min_val:
            return 0
        width = self.width() - self.handle_width
        ratio = (val - self.min_val) / (self.max_val - self.min_val)
        return int(ratio * width) + self.handle_width // 2

    def pos_to_value(self, pos_x):
        width = self.width() - self.handle_width
        if width <= 0:
            return self.min_val
        pos_x = pos_x - self.handle_width // 2
        ratio = pos_x / width
        ratio = max(0.0, min(ratio, 1.0))
        val = int(self.min_val + ratio * (self.max_val - self.min_val))
        return val

    def get_handle_rects(self):
        y = (self.height() - self.handle_height) // 2
        pos_l = self.value_to_pos(self.start_val)
        pos_r = self.value_to_pos(self.end_val)
        rect_l = QRect(pos_l - self.handle_width // 2, y, self.handle_width, self.handle_height)
        rect_r = QRect(pos_r - self.handle_width // 2, y, self.handle_width, self.handle_height)
        return rect_l, rect_r

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        track_height = 6
        track_y = (self.height() - track_height) // 2
        track_rect = QRect(self.handle_width // 2, track_y, self.width() - self.handle_width, track_height)
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#d2d0ce")))
        painter.drawRoundedRect(track_rect, 3, 3)
        
        pos_l = self.value_to_pos(self.start_val)
        pos_r = self.value_to_pos(self.end_val)
        
        active_rect = QRect(pos_l, track_y, pos_r - pos_l, track_height)
        painter.setBrush(QBrush(QColor("#0078d4")))
        painter.drawRoundedRect(active_rect, 3, 3)
        
        rect_l, rect_r = self.get_handle_rects()
        
        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.setPen(QPen(QColor("#0078d4"), 2))
        painter.drawRoundedRect(rect_l, 4, 4)
        
        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.setPen(QPen(QColor("#e81123"), 2))
        painter.drawRoundedRect(rect_r, 4, 4)
        
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            rect_l, rect_r = self.get_handle_rects()
            
            dist_l = abs(pos.x() - (rect_l.x() + rect_l.width() // 2))
            dist_r = abs(pos.x() - (rect_r.x() + rect_r.width() // 2))
            
            if dist_l <= self.handle_width and dist_l < dist_r:
                self.active_handle = "left"
            elif dist_r <= self.handle_width:
                self.active_handle = "right"
            else:
                if dist_l < dist_r:
                    self.active_handle = "left"
                    val = self.pos_to_value(pos.x())
                    self.start_val = max(self.min_val, min(val, self.end_val - 1))
                    self.rangeChanged.emit(self.start_val, self.end_val)
                    self.update()
                else:
                    self.active_handle = "right"
                    val = self.pos_to_value(pos.x())
                    self.end_val = max(self.start_val + 1, min(val, self.max_val))
                    self.rangeChanged.emit(self.start_val, self.end_val)
                    self.update()
            self.sliderPressed.emit()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.active_handle:
            pos = event.position().toPoint()
            val = self.pos_to_value(pos.x())
            
            if self.active_handle == "left":
                self.start_val = max(self.min_val, min(val, self.end_val - 1))
            elif self.active_handle == "right":
                self.end_val = max(self.start_val + 1, min(val, self.max_val))
                
            self.rangeChanged.emit(self.start_val, self.end_val)
            self.update()
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.active_handle = None
            self.sliderReleased.emit()
            event.accept()


class VideoPlayerLabel(QLabel):
    cropRectChanged = Signal(int, int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: black; border: 1px solid #d0d0d0; border-radius: 5px;")
        
        self.current_pixmap = None
        self.crop_x = 0
        self.crop_y = 0
        self.crop_w = 100
        self.crop_h = 100
        self.orig_w = 100
        self.orig_h = 100
        self.aspect_ratio = None
        
        self.drag_mode = None
        self.press_pos = None
        self.start_crop_rect = None
        
        self.setMouseTracking(True)

    def set_pixmap(self, pixmap):
        self.current_pixmap = pixmap
        self.update()

    def set_media_size(self, orig_w, orig_h):
        self.orig_w = orig_w
        self.orig_h = orig_h
        self.update()

    def set_crop_rect(self, x, y, w, h):
        self.crop_x = x
        self.crop_y = y
        self.crop_w = w
        self.crop_h = h
        self.update()

    def set_aspect_ratio(self, ratio):
        self.aspect_ratio = ratio
        self.update()

    def get_draw_geometry(self):
        if self.orig_w <= 0 or self.orig_h <= 0 or not self.current_pixmap:
            return None
            
        lbl_w = self.width()
        lbl_h = self.height()
        if lbl_w <= 0 or lbl_h <= 0:
            return None
            
        pix_size = self.current_pixmap.size()
        ratio_video = pix_size.width() / pix_size.height()
        ratio_widget = lbl_w / lbl_h
        
        if ratio_video > ratio_widget:
            display_w = lbl_w
            display_h = int(lbl_w / ratio_video)
            offset_x = 0
            offset_y = (lbl_h - display_h) // 2
        else:
            display_h = lbl_h
            display_w = int(lbl_h * ratio_video)
            offset_x = (lbl_w - display_w) // 2
            offset_y = 0
            
        scale_x = display_w / self.orig_w
        scale_y = display_h / self.orig_h
        
        draw_x = int(self.crop_x * scale_x) + offset_x
        draw_y = int(self.crop_y * scale_y) + offset_y
        draw_w = int(self.crop_w * scale_x)
        draw_h = int(self.crop_h * scale_y)
        
        return draw_x, draw_y, draw_w, draw_h, scale_x, scale_y, offset_x, offset_y, display_w, display_h

    def get_drag_mode_at(self, pos):
        geom = self.get_draw_geometry()
        if not geom:
            return None
        draw_x, draw_y, draw_w, draw_h, _, _, offset_x, offset_y, display_w, display_h = geom
        
        mx, my = pos.x(), pos.y()
        if mx < offset_x or mx > offset_x + display_w or my < offset_y or my > offset_y + display_h:
            return None
            
        handle = 10
        
        near_l = abs(mx - draw_x) <= handle
        near_r = abs(mx - (draw_x + draw_w)) <= handle
        near_t = abs(my - draw_y) <= handle
        near_b = abs(my - (draw_y + draw_h)) <= handle
        
        if near_l and near_t: return "resize_tl"
        if near_r and near_t: return "resize_tr"
        if near_l and near_b: return "resize_bl"
        if near_r and near_b: return "resize_br"
        if near_l and (draw_y <= my <= draw_y + draw_h): return "resize_l"
        if near_r and (draw_y <= my <= draw_y + draw_h): return "resize_r"
        if near_t and (draw_x <= mx <= draw_x + draw_w): return "resize_t"
        if near_b and (draw_x <= mx <= draw_x + draw_w): return "resize_b"
        if draw_x < mx < draw_x + draw_w and draw_y < my < draw_y + draw_h: return "move"
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            mode = self.get_drag_mode_at(event.position().toPoint())
            if mode:
                self.drag_mode = mode
                self.press_pos = event.position().toPoint()
                self.start_crop_rect = (self.crop_x, self.crop_y, self.crop_w, self.crop_h)
                event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_mode = None
            self.press_pos = None
            self.start_crop_rect = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        
        if not self.drag_mode:
            mode = self.get_drag_mode_at(pos)
            if mode == "move":
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            elif mode in ("resize_tl", "resize_br"):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif mode in ("resize_tr", "resize_bl"):
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif mode in ("resize_l", "resize_r"):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif mode in ("resize_t", "resize_b"):
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
            
        geom = self.get_draw_geometry()
        if not geom or not self.press_pos or not self.start_crop_rect:
            return
            
        _, _, _, _, scale_x, scale_y, _, _, _, _ = geom
        
        dx = int((pos.x() - self.press_pos.x()) / scale_x)
        dy = int((pos.y() - self.press_pos.y()) / scale_y)
        
        sx, sy, sw, sh = self.start_crop_rect
        nx, ny, nw, nh = sx, sy, sw, sh
        
        if self.drag_mode == "move":
            nx = sx + dx
            ny = sy + dy
            nx = max(0, min(nx, self.orig_w - sw))
            ny = max(0, min(ny, self.orig_h - sh))
            
        elif self.drag_mode == "resize_r":
            nw = sw + dx
            nw = max(10, min(nw, self.orig_w - sx))
            if self.aspect_ratio:
                nh = int(nw / self.aspect_ratio)
                if sy + nh > self.orig_h:
                    nh = self.orig_h - sy
                    nw = int(nh * self.aspect_ratio)
            
        elif self.drag_mode == "resize_l":
            nx = sx + dx
            nw = sw - dx
            if nx < 0:
                nx = 0
                nw = sx + sw
            if nw < 10:
                nw = 10
                nx = sx + sw - 10
            if self.aspect_ratio:
                nh = int(nw / self.aspect_ratio)
                if sy + nh > self.orig_h:
                    nh = self.orig_h - sy
                    nw = int(nh * self.aspect_ratio)
                    nx = sx + sw - nw

        elif self.drag_mode == "resize_b":
            if self.aspect_ratio:
                pass
            else:
                nh = sh + dy
                nh = max(10, min(nh, self.orig_h - sy))
                
        elif self.drag_mode == "resize_t":
            if self.aspect_ratio:
                pass
            else:
                ny = sy + dy
                nh = sh - dy
                if ny < 0:
                    ny = 0
                    nh = sy + sh
                if nh < 10:
                    nh = 10
                    ny = sy + sh - 10
                    
        elif self.drag_mode in ("resize_tl", "resize_tr", "resize_bl", "resize_br"):
            if self.drag_mode == "resize_br":
                nw = sw + dx
                if self.aspect_ratio:
                    nh = int(nw / self.aspect_ratio)
                else:
                    nh = sh + dy
            elif self.drag_mode == "resize_bl":
                nx = sx + dx
                nw = sw - dx
                if nx < 0:
                    nx = 0
                    nw = sx + sw
                if nw < 10:
                    nw = 10
                    nx = sx + sw - 10
                if self.aspect_ratio:
                    nh = int(nw / self.aspect_ratio)
                else:
                    nh = sh + dy
            elif self.drag_mode == "resize_tr":
                nw = sw + dx
                if self.aspect_ratio:
                    nh = int(nw / self.aspect_ratio)
                    ny = sy - (nh - sh)
                    if ny < 0:
                        ny = 0
                        nh = sy + sh
                        nw = int(nh * self.aspect_ratio)
                else:
                    ny = sy + dy
                    nh = sh - dy
                    if ny < 0:
                        ny = 0
                        nh = sy + sh
                    if nh < 10:
                        nh = 10
                        ny = sy + sh - 10
            elif self.drag_mode == "resize_tl":
                nx = sx + dx
                nw = sw - dx
                if nx < 0:
                    nx = 0
                    nw = sx + sw
                if nw < 10:
                    nw = 10
                    nx = sx + sw - 10
                if self.aspect_ratio:
                    nh = int(nw / self.aspect_ratio)
                    ny = sy - (nh - sh)
                    if ny < 0:
                        ny = 0
                        nh = sy + sh
                        nw = int(nh * self.aspect_ratio)
                        nx = sx + sw - nw
                else:
                    ny = sy + dy
                    nh = sh - dy
                    if ny < 0:
                        ny = 0
                        nh = sy + sh
                    if nh < 10:
                        nh = 10
                        ny = sy + sh - 10

        if self.aspect_ratio:
            nw = max(10, min(nw, self.orig_w - nx))
            nh = int(nw / self.aspect_ratio)
            if ny + nh > self.orig_h:
                nh = self.orig_h - ny
                nw = int(nh * self.aspect_ratio)
        else:
            nw = max(10, min(nw, self.orig_w - nx))
            nh = max(10, min(nh, self.orig_h - ny))
            
        self.crop_x = nx
        self.crop_y = ny
        self.crop_w = nw
        self.crop_h = nh
        self.update()
        
        self.cropRectChanged.emit(self.crop_x, self.crop_y, self.crop_w, self.crop_h)
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 1. Vẽ khung hình video (nếu có)
        geom = self.get_draw_geometry()
        if geom:
            draw_x, draw_y, draw_w, draw_h, _, _, offset_x, offset_y, display_w, display_h = geom
            
            # Vẽ ảnh video
            if self.current_pixmap:
                rect_display = QRect(offset_x, offset_y, display_w, display_h)
                painter.drawPixmap(rect_display, self.current_pixmap)
                
            # Fill phủ mờ màu tối bên ngoài khung crop
            overlay_color = QColor(0, 0, 0, 165)
            painter.fillRect(offset_x, offset_y, display_w, draw_y - offset_y, overlay_color)
            painter.fillRect(offset_x, draw_y + draw_h, display_w, offset_y + display_h - (draw_y + draw_h), overlay_color)
            painter.fillRect(offset_x, draw_y, draw_x - offset_x, draw_h, overlay_color)
            painter.fillRect(draw_x + draw_w, draw_y, offset_x + display_w - (draw_x + draw_w), draw_h, overlay_color)
            
            # Vẽ viền xanh lá quanh khung Crop
            painter.setPen(QPen(QColor("#00ff00"), 2, Qt.PenStyle.SolidLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(draw_x, draw_y, draw_w, draw_h)
            
            # Vẽ 4 chấm tròn/vuông nhỏ ở 4 góc để làm tay nắm
            painter.setBrush(QBrush(QColor("#00ff00")))
            hs = 6
            painter.drawRect(draw_x - hs//2, draw_y - hs//2, hs, hs)
            painter.drawRect(draw_x + draw_w - hs//2, draw_y - hs//2, hs, hs)
            painter.drawRect(draw_x - hs//2, draw_y + draw_h - hs//2, hs, hs)
            painter.drawRect(draw_x + draw_w - hs//2, draw_y + draw_h - hs//2, hs, hs)
        else:
            # Nếu chưa nạp video
            painter.setPen(QColor("#aaa"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Chưa nạp video để hiển thị xem trước.")
            
        painter.end()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bộ chuyển đổi phương tiện đa năng (Ảnh, Video, Audio)")
        self.setMinimumSize(1000, 800)

        # Trạng thái Tab 1: Ảnh
        self.file_list_img = []
        self.file_row_map_img = {}
        self.last_scroll_time_img = 0
        self.custom_output_dir_img = ""
        self.worker_img = None

        # Trạng thái Tab 2: Video
        self.file_list_vid = []
        self.file_row_map_vid = {}
        self.last_scroll_time_vid = 0
        self.custom_output_dir_vid = ""
        self.worker_vid = None

        # Trạng thái Tab 3: Cắt & Khung Video
        self.file_path_edit = ""
        self.cap = None
        self.total_frames = 0
        self.fps = 30.0
        self.video_width = 100
        self.video_height = 100
        self.duration = 0.0
        self.custom_output_dir_edit = ""
        self.worker_edit = None
        self.trim_start_frame = 0
        self.trim_end_frame = 0
        
        # QMediaPlayer và QAudioOutput phục vụ chạy thử có tiếng ở Tab 3
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        
        # Đồng bộ sự kiện thay đổi tiến trình phát để cập nhật thanh timeline
        self.media_player.positionChanged.connect(self.on_player_position_changed)
        self.media_player.durationChanged.connect(self.on_player_duration_changed)
        
        self.is_playing = False

        self.init_ui()
        self.check_jxl_support()

    def init_ui(self):
        # 1. Tạo Outer QTabWidget làm widget trung tâm của cửa sổ chính
        self.outer_tab_widget = QTabWidget()
        # Áp dụng CSS để tạo viền tab phẳng đẹp mắt như hình
        self.outer_tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 2px solid #0078d4;
                border-radius: 6px;
                background-color: #ffffff;
            }
            QTabBar::tab {
                background: #e1dfdd;
                border: 1px solid #c8c6c4;
                border-bottom: none;
                padding: 8px 25px;
                font-weight: bold;
                font-size: 13px;
                color: #323130;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 4px;
            }
            QTabBar::tab:hover {
                background: #d2d0ce;
                color: #000000;
            }
            QTabBar::tab:selected {
                background: #0078d4;
                color: white;
                border: 1px solid #0078d4;
                border-bottom: none;
            }
        """)
        self.setCentralWidget(self.outer_tab_widget)

        # TAB 1: File (chứa Inner QTabWidget)
        self.tab_file = QWidget()
        file_layout = QVBoxLayout(self.tab_file)
        file_layout.setContentsMargins(5, 5, 5, 5)

        self.inner_tab_widget = QTabWidget()
        self.inner_tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 2px solid #107c41;
                border-radius: 5px;
                background-color: #ffffff;
            }
            QTabBar::tab {
                background: #f3f2f1;
                border: 1px solid #d2d0ce;
                border-bottom: none;
                padding: 6px 18px;
                font-size: 13px;
                color: #323130;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
                margin-right: 3px;
            }
            QTabBar::tab:hover {
                background: #edebe9;
                color: #000000;
            }
            QTabBar::tab:selected {
                background: #107c41;
                color: white;
                font-weight: bold;
                border: 1px solid #107c41;
                border-bottom: none;
            }
        """)
        file_layout.addWidget(self.inner_tab_widget)

        self.tab_image = QWidget()
        self.tab_video = QWidget()
        self.tab_editor = QWidget()

        self.create_image_tab()
        self.create_video_tab()
        self.create_editor_tab()

        self.inner_tab_widget.addTab(self.tab_image, "Chuyển đổi Ảnh")
        self.inner_tab_widget.addTab(self.tab_video, "Chuyển đổi Video / Âm thanh")
        if OPENCV_AVAILABLE:
            self.inner_tab_widget.addTab(self.tab_editor, "Cắt & Khung Video (Trim/Crop)")

        self.outer_tab_widget.addTab(self.tab_file, "File")

        # TAB 2: Cách sử dụng các tính năng
        self.tab_usage = QWidget()
        usage_layout = QVBoxLayout(self.tab_usage)
        usage_layout.setContentsMargins(10, 10, 10, 10)
        
        self.txt_usage = QTextBrowser()
        self.txt_usage.setOpenExternalLinks(True)
        self.txt_usage.setHtml(self.get_usage_html())
        usage_layout.addWidget(self.txt_usage)
        
        self.outer_tab_widget.addTab(self.tab_usage, "Cách sử dụng các tính năng")

        # TAB 3: About
        self.tab_about = QWidget()
        about_layout = QVBoxLayout(self.tab_about)
        about_layout.setContentsMargins(10, 10, 10, 10)
        
        self.txt_about = QTextBrowser()
        self.txt_about.setOpenExternalLinks(True)
        self.txt_about.setHtml(self.get_about_html())
        about_layout.addWidget(self.txt_about)
        
        self.outer_tab_widget.addTab(self.tab_about, "About")

    def get_usage_html(self):
        return """
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; padding: 15px;">
            <h2 style="color: #0078d4; border-bottom: 2px solid #0078d4; padding-bottom: 5px;">HƯỚNG DẪN SỬ DỤNG CÁC TÍNH NĂNG</h2>
            
            <h3 style="color: #2b579a;">1. Chuyển đổi Ảnh (Tab "Chuyển đổi Ảnh")</h3>
            <p>Hỗ trợ kéo thả hoặc click đúp chọn các tệp tin ảnh: <b>JXL, JPG, PNG, WebP, BMP, TIFF</b>.</p>
            <ul>
                <li>Chọn định dạng đích mong muốn trong hộp thả xuống.</li>
                <li>Với định dạng <b>JPEG</b> hoặc <b>WebP</b>, bạn có thể chỉnh chất lượng nén bằng thanh trượt.</li>
                <li>Thiết lập tiền tố/hậu tố đổi tên file (nếu muốn) và chọn thư mục lưu (mặc định lưu cùng thư mục gốc).</li>
                <li>Nhấn <b>Bắt đầu chuyển đổi</b> để xử lý.</li>
            </ul>

            <h3 style="color: #2b579a;">2. Chuyển đổi Video / Âm thanh (Tab "Chuyển đổi Video / Âm thanh")</h3>
            <p>Hỗ trợ kéo thả các tệp tin video: <b>MP4, MKV, AVI, MOV, WebM, FLV, WMV</b>.</p>
            <ul>
                <li><b>Tách nhạc MP3:</b> Chọn lưu định dạng <b>MP3 (Tách nhạc)</b> để tự động trích xuất luồng âm thanh chất lượng cao bằng FFmpeg.</li>
                <li><b>Nén dung lượng Video:</b> Chọn các định dạng MP4/WebM/MKV/AVI và chọn mức nén: <b>Cao (Gốc)</b>, <b>Trung bình (Tối ưu)</b>, hoặc <b>Thấp (Nén nhỏ)</b>.</li>
                <li><b>Trích xuất ảnh đại diện:</b> Chọn định dạng lưu <b>JPEG</b> để lấy khung hình đầu tiên của video.</li>
            </ul>

            <h3 style="color: #2b579a;">3. Cắt ngắn & Cắt khung Video (Tab "Cắt & Khung Video")</h3>
            <p>Cho phép bạn chỉnh sửa nhanh một tệp video trực quan bằng cách kéo thả vào cột bên trái.</p>
            <ul>
                <li><b>Cắt ngắn video (Trim):</b> Di chuyển thanh trượt <b>Điểm đầu</b> và <b>Điểm cuối</b> để chọn đoạn muốn lấy. Khung hình xem trước sẽ nhảy đúng đến điểm bạn chọn.</li>
                <li><b>Cắt khung hình (Crop):</b> Chọn tỷ lệ khung hình (16:9, 9:16, 1:1, 4:3, Tự do). Sử dụng các thanh trượt vị trí X, Y, Width, Height để di chuyển và định cỡ khung cắt. Khung cắt được biểu thị bằng <b>viền xanh neon</b> cực kỳ trực quan.</li>
                <li>Nhấn <b>Cắt & Lưu Video</b> để thực hiện (File kết quả sẽ có hậu tố <code>_edited</code>).</li>
            </ul>

            <h3 style="color: #c7254e; background-color: #f9f2f4; padding: 8px; border-radius: 4px;">* Yêu cầu về FFmpeg:</h3>
            <p>Các tính năng về Video/Audio yêu cầu tệp <b>ffmpeg.exe</b> nằm ở đường dẫn thư mục: <code>ffmpeg/ffmpeg.exe</code> (nằm ngay cạnh tệp chạy <code>run.bat</code> của chương trình).</p>
        </body>
        </html>
        """

    def get_about_html(self):
        return """
        <html>
        <body style="font-family: Arial, sans-serif; text-align: center; padding: 30px; color: #333;">
            <h1 style="color: #0078d4; margin-bottom: 5px;">BỘ CHUYỂN ĐỔI PHƯƠNG TIỆN ĐA NĂNG</h1>
            <p style="color: #666; font-size: 14px; margin-bottom: 30px;">Phiên bản Pro v2.0</p>
            
            <div style="background-color: #f9f9f9; border: 1px solid #e0e0e0; border-radius: 10px; padding: 25px; display: inline-block; text-align: left; min-width: 320px; box-shadow: 0 2px 5px rgba(0,0,0,0.05);">
                <p style="margin: 8px 0;"><b>Tác giả:</b> Phạm Thanh Bình</p>
                <p style="margin: 8px 0;"><b>Facebook cá nhân:</b> <a href="https://www.facebook.com/ptbinh1912" style="color: #0078d4; font-weight: bold; text-decoration: none;">ptbinh1912</a></p>
                <p style="margin: 8px 0;"><b>Công nghệ:</b> Python, PySide6, OpenCV, Pillow, FFmpeg</p>
            </div>
            
            <p style="color: #999; font-size: 11px; margin-top: 50px;">© 2026 Phạm Thanh Bình. Tất cả các quyền được bảo lưu.</p>
        </body>
        </html>
        """

    def create_image_tab(self):
        layout = QVBoxLayout(self.tab_image)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        self.drop_zone_img = DropZone(mode="image")
        self.drop_zone_img.filesDropped.connect(self.handle_files_added_img)
        layout.addWidget(self.drop_zone_img)

        self.table_img = QTableWidget()
        self.table_img.setColumnCount(4)
        self.table_img.setHorizontalHeaderLabels(["Tên tệp", "Đường dẫn gốc", "Kích thước", "Trạng thái"])
        self.table_img.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_img.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_img.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_img.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_img.setAlternatingRowColors(True)
        self.table_img.setStyleSheet("""
            QTableWidget {
                background-color: #ffffff;
                alternate-background-color: #f7f7f7;
                gridline-color: #e0e0e0;
                border: 1px solid #d0d0d0;
                border-radius: 5px;
            }
            QHeaderView::section {
                background-color: #f3f3f3;
                padding: 6px;
                border: 1px solid #d0d0d0;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.table_img)

        config_layout = QHBoxLayout()

        fmt_group = QGroupBox("Định dạng đầu ra")
        fmt_group_layout = QVBoxLayout(fmt_group)
        self.combo_format_img = QComboBox()
        self.combo_format_img.addItems(["JPEG (.jpg)", "PNG (.png)", "WebP (.webp)", "BMP (.bmp)", "TIFF (.tiff)"])
        self.combo_format_img.currentTextChanged.connect(self.handle_format_changed_img)
        fmt_group_layout.addWidget(self.combo_format_img)
        config_layout.addWidget(fmt_group, 1)

        dir_group = QGroupBox("Thư mục lưu kết quả")
        dir_group_layout = QVBoxLayout(dir_group)
        self.radio_same_img = QRadioButton("Lưu cùng thư mục gốc")
        self.radio_same_img.setChecked(True)
        self.radio_same_img.toggled.connect(self.toggle_output_mode_img)
        
        self.radio_custom_img = QRadioButton("Lưu thư mục tùy chỉnh:")
        self.radio_custom_img.toggled.connect(self.toggle_output_mode_img)
        
        custom_path_layout = QHBoxLayout()
        self.lbl_custom_path_img = QLabel("Chưa chọn...")
        self.lbl_custom_path_img.setStyleSheet("color: #777; padding-left: 20px; font-style: italic;")
        self.btn_select_dir_img = QPushButton("Chọn thư mục")
        self.btn_select_dir_img.setEnabled(False)
        self.btn_select_dir_img.clicked.connect(self.select_custom_directory_img)
        custom_path_layout.addWidget(self.lbl_custom_path_img, 1)
        custom_path_layout.addWidget(self.btn_select_dir_img)

        dir_group_layout.addWidget(self.radio_same_img)
        dir_group_layout.addWidget(self.radio_custom_img)
        dir_group_layout.addLayout(custom_path_layout)
        config_layout.addWidget(dir_group, 2)

        self.quality_group_img = QGroupBox("Chất lượng JPEG đầu ra")
        quality_layout = QVBoxLayout(self.quality_group_img)
        self.slider_quality_img = QSlider(Qt.Orientation.Horizontal)
        self.slider_quality_img.setMinimum(10)
        self.slider_quality_img.setMaximum(100)
        self.slider_quality_img.setValue(90)
        self.slider_quality_img.setTickInterval(10)
        self.slider_quality_img.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_quality_img.valueChanged.connect(self.update_quality_label)
        
        self.lbl_quality_val_img = QLabel("90% (Khuyên dùng)")
        self.lbl_quality_val_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_quality_val_img.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        
        quality_layout.addWidget(self.slider_quality_img)
        quality_layout.addWidget(self.lbl_quality_val_img)
        config_layout.addWidget(self.quality_group_img, 1)

        layout.addLayout(config_layout)

        rename_group = QGroupBox("Đổi tên file đầu ra (Tùy chọn)")
        rename_layout = QHBoxLayout(rename_group)
        rename_layout.addWidget(QLabel("Tiền tố (Prefix):"))
        self.txt_prefix_img = QLineEdit()
        self.txt_prefix_img.setPlaceholderText("Ví dụ: converted_")
        rename_layout.addWidget(self.txt_prefix_img)
        
        rename_layout.addWidget(QLabel("Hậu tố (Suffix):"))
        self.txt_suffix_img = QLineEdit()
        self.txt_suffix_img.setPlaceholderText("Ví dụ: _compressed")
        rename_layout.addWidget(self.txt_suffix_img)
        layout.addWidget(rename_group)

        ctrl_layout = QHBoxLayout()
        self.progress_bar_img = QProgressBar()
        self.progress_bar_img.setVisible(False)
        self.progress_bar_img.setStyleSheet("""
            QProgressBar { border: 1px solid #d0d0d0; border-radius: 5px; text-align: center; height: 25px; }
            QProgressBar::chunk { background-color: #0078d4; width: 10px; }
        """)
        
        self.btn_clear_img = QPushButton("Xóa danh sách")
        self.btn_clear_img.setMinimumHeight(35)
        self.btn_clear_img.clicked.connect(self.clear_list_img)

        self.btn_open_dir_img = QPushButton("Mở thư mục lưu")
        self.btn_open_dir_img.setMinimumHeight(35)
        self.btn_open_dir_img.clicked.connect(self.open_output_directory_img)
        
        self.btn_convert_img = QPushButton("Bắt đầu chuyển đổi")
        self.btn_convert_img.setMinimumHeight(35)
        self.btn_convert_img.setStyleSheet("""
            QPushButton { background-color: #0078d4; color: white; font-weight: bold; border-radius: 5px; padding: 0 20px; }
            QPushButton:hover { background-color: #106ebe; }
            QPushButton:pressed { background-color: #005a9e; }
        """)
        self.btn_convert_img.clicked.connect(self.start_conversion_img)

        ctrl_layout.addWidget(self.progress_bar_img, 1)
        ctrl_layout.addWidget(self.btn_clear_img)
        ctrl_layout.addWidget(self.btn_open_dir_img)
        ctrl_layout.addWidget(self.btn_convert_img)
        layout.addLayout(ctrl_layout)

        self.lbl_status_img = QLabel("Chưa có ảnh nào được thêm vào.")
        self.lbl_status_img.setStyleSheet("color: #555555;")
        layout.addWidget(self.lbl_status_img)

    def create_video_tab(self):
        layout = QVBoxLayout(self.tab_video)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        self.drop_zone_vid = DropZone(mode="video")
        self.drop_zone_vid.filesDropped.connect(self.handle_files_added_vid)
        layout.addWidget(self.drop_zone_vid)

        self.table_vid = QTableWidget()
        self.table_vid.setColumnCount(4)
        self.table_vid.setHorizontalHeaderLabels(["Tên tệp", "Đường dẫn gốc", "Kích thước", "Trạng thái"])
        self.table_vid.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_vid.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_vid.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_vid.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_vid.setAlternatingRowColors(True)
        self.table_vid.setStyleSheet("""
            QTableWidget {
                background-color: #ffffff;
                alternate-background-color: #f7f7f7;
                gridline-color: #e0e0e0;
                border: 1px solid #d0d0d0;
                border-radius: 5px;
            }
            QHeaderView::section {
                background-color: #f3f3f3;
                padding: 6px;
                border: 1px solid #d0d0d0;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.table_vid)

        config_layout = QHBoxLayout()

        fmt_group = QGroupBox("Định dạng đầu ra")
        fmt_group_layout = QVBoxLayout(fmt_group)
        self.combo_format_vid = QComboBox()
        self.combo_format_vid.addItems(["MP4 (.mp4)", "WebM (.webm)", "MKV (.mkv)", "AVI (.avi)", "MP3 (Tách nhạc)", "JPEG (Ảnh trích xuất)"])
        self.combo_format_vid.currentTextChanged.connect(self.handle_format_changed_vid)
        fmt_group_layout.addWidget(self.combo_format_vid)
        config_layout.addWidget(fmt_group, 1)

        dir_group = QGroupBox("Thư mục lưu kết quả")
        dir_group_layout = QVBoxLayout(dir_group)
        self.radio_same_vid = QRadioButton("Lưu cùng thư mục gốc")
        self.radio_same_vid.setChecked(True)
        self.radio_same_vid.toggled.connect(self.toggle_output_mode_vid)
        
        self.radio_custom_vid = QRadioButton("Lưu thư mục tùy chỉnh:")
        self.radio_custom_vid.toggled.connect(self.toggle_output_mode_vid)
        
        custom_path_layout = QHBoxLayout()
        self.lbl_custom_path_vid = QLabel("Chưa chọn...")
        self.lbl_custom_path_vid.setStyleSheet("color: #777; padding-left: 20px; font-style: italic;")
        self.btn_select_dir_vid = QPushButton("Chọn thư mục")
        self.btn_select_dir_vid.setEnabled(False)
        self.btn_select_dir_vid.clicked.connect(self.select_custom_directory_vid)
        custom_path_layout.addWidget(self.lbl_custom_path_vid, 1)
        custom_path_layout.addWidget(self.btn_select_dir_vid)

        dir_group_layout.addWidget(self.radio_same_vid)
        dir_group_layout.addWidget(self.radio_custom_vid)
        dir_group_layout.addLayout(custom_path_layout)
        config_layout.addWidget(dir_group, 2)

        self.video_quality_group = QGroupBox("Chất lượng / Nén Video")
        video_quality_layout = QVBoxLayout(self.video_quality_group)
        self.combo_video_quality = QComboBox()
        self.combo_video_quality.addItems(["Cao (Gốc)", "Trung bình (Tối ưu)", "Thấp (Nén nhỏ)"])
        self.combo_video_quality.setCurrentIndex(1)
        video_quality_layout.addWidget(self.combo_video_quality)
        config_layout.addWidget(self.video_quality_group, 1)

        layout.addLayout(config_layout)

        rename_group_vid = QGroupBox("Đổi tên file đầu ra (Tùy chọn)")
        rename_layout_vid = QHBoxLayout(rename_group_vid)
        rename_layout_vid.addWidget(QLabel("Tiền tố (Prefix):"))
        self.txt_prefix_vid = QLineEdit()
        self.txt_prefix_vid.setPlaceholderText("Ví dụ: converted_")
        rename_layout_vid.addWidget(self.txt_prefix_vid)
        
        rename_layout_vid.addWidget(QLabel("Hậu tố (Suffix):"))
        self.txt_suffix_vid = QLineEdit()
        self.txt_suffix_vid.setPlaceholderText("Ví dụ: _compress")
        rename_layout_vid.addWidget(self.txt_suffix_vid)
        layout.addWidget(rename_group_vid)

        ctrl_layout = QHBoxLayout()
        self.progress_bar_vid = QProgressBar()
        self.progress_bar_vid.setVisible(False)
        self.progress_bar_vid.setStyleSheet("""
            QProgressBar { border: 1px solid #d0d0d0; border-radius: 5px; text-align: center; height: 25px; }
            QProgressBar::chunk { background-color: #228b22; width: 10px; }
        """)
        
        self.btn_clear_vid = QPushButton("Xóa danh sách")
        self.btn_clear_vid.setMinimumHeight(35)
        self.btn_clear_vid.clicked.connect(self.clear_list_vid)

        self.btn_open_dir_vid = QPushButton("Mở thư mục lưu")
        self.btn_open_dir_vid.setMinimumHeight(35)
        self.btn_open_dir_vid.clicked.connect(self.open_output_directory_vid)
        
        self.btn_convert_vid = QPushButton("Bắt đầu chuyển đổi")
        self.btn_convert_vid.setMinimumHeight(35)
        self.btn_convert_vid.setStyleSheet("""
            QPushButton { background-color: #228b22; color: white; font-weight: bold; border-radius: 5px; padding: 0 20px; }
            QPushButton:hover { background-color: #1e781e; }
            QPushButton:pressed { background-color: #145014; }
        """)
        self.btn_convert_vid.clicked.connect(self.start_conversion_vid)

        ctrl_layout.addWidget(self.progress_bar_vid, 1)
        ctrl_layout.addWidget(self.btn_clear_vid)
        ctrl_layout.addWidget(self.btn_open_dir_vid)
        ctrl_layout.addWidget(self.btn_convert_vid)
        layout.addLayout(ctrl_layout)

        self.lbl_status_vid = QLabel("Chưa có video nào được thêm vào.")
        self.lbl_status_vid.setStyleSheet("color: #555555;")
        layout.addWidget(self.lbl_status_vid)

    def create_editor_tab(self):
        main_layout = QHBoxLayout(self.tab_editor)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        if not OPENCV_AVAILABLE:
            error_lbl = QLabel(
                "Lỗi: Không tìm thấy thư viện OpenCV (opencv-python).\n"
                "Vui lòng cài đặt OpenCV bằng cách chạy lệnh sau trong terminal:\n"
                "pip install opencv-python\n"
                "Sau đó khởi động lại ứng dụng."
            )
            error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            error_lbl.setStyleSheet("color: red; font-size: 16px; font-weight: bold;")
            main_layout.addWidget(error_lbl)
            return

        # --- CỘT TRÁI: ĐIỀU KHIỂN & CẤU HÌNH ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(5, 5, 10, 5)
        left_layout.setSpacing(12)

        # Tiêu đề
        lbl_title = QLabel("CẮT NGẮN & CẮT KHUNG VIDEO")
        lbl_title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color: #0078d4;")
        left_layout.addWidget(lbl_title)

        # Dropzone nạp video
        self.drop_zone_edit = DropZone(mode="video")
        self.drop_zone_edit.filesDropped.connect(self.handle_file_added_edit)
        left_layout.addWidget(self.drop_zone_edit)

        # Thông tin video
        self.lbl_video_info = QLabel("Thông tin: Chưa nạp video nào.")
        self.lbl_video_info.setWordWrap(True)
        self.lbl_video_info.setStyleSheet("color: #555; background-color: #f0f0f0; padding: 8px; border-radius: 5px;")
        left_layout.addWidget(self.lbl_video_info)

        # --- PHẦN 1: CẤU HÌNH CẮT KHUNG (CROP) ---
        crop_box = QGroupBox("Cấu hình Cắt Khung (Crop Video)")
        crop_layout = QVBoxLayout(crop_box)
        crop_layout.setSpacing(8)

        # Bộ chọn tỉ lệ phổ thông
        ratio_layout = QHBoxLayout()
        ratio_layout.addWidget(QLabel("Tỷ lệ khung:"))
        self.combo_crop_ratio = QComboBox()
        self.combo_crop_ratio.addItems(["Tự do (Free)", "16:9 (Ngang)", "9:16 (Dọc TikTok/Shorts)", "1:1 (Vuông)", "4:3 (Cổ điển)"])
        self.combo_crop_ratio.currentTextChanged.connect(self.on_crop_ratio_changed)
        ratio_layout.addWidget(self.combo_crop_ratio, 1)
        crop_layout.addLayout(ratio_layout)

        # Slider vị trí X
        x_layout = QHBoxLayout()
        self.lbl_crop_x = QLabel("Vị trí X:")
        self.lbl_crop_x.setFixedWidth(60)
        self.slider_crop_x = QSlider(Qt.Orientation.Horizontal)
        self.slider_crop_x.setEnabled(False)
        self.slider_crop_x.valueChanged.connect(self.on_crop_slider_moved)
        x_layout.addWidget(self.lbl_crop_x)
        x_layout.addWidget(self.slider_crop_x)
        crop_layout.addLayout(x_layout)

        # Slider vị trí Y
        y_layout = QHBoxLayout()
        self.lbl_crop_y = QLabel("Vị trí Y:")
        self.lbl_crop_y.setFixedWidth(60)
        self.slider_crop_y = QSlider(Qt.Orientation.Horizontal)
        self.slider_crop_y.setEnabled(False)
        self.slider_crop_y.valueChanged.connect(self.on_crop_slider_moved)
        y_layout.addWidget(self.lbl_crop_y)
        y_layout.addWidget(self.slider_crop_y)
        crop_layout.addLayout(y_layout)

        # Slider Chiều rộng
        w_layout = QHBoxLayout()
        self.lbl_crop_w = QLabel("Rộng (W):")
        self.lbl_crop_w.setFixedWidth(60)
        self.slider_crop_w = QSlider(Qt.Orientation.Horizontal)
        self.slider_crop_w.setEnabled(False)
        self.slider_crop_w.valueChanged.connect(self.on_crop_slider_moved)
        w_layout.addWidget(self.lbl_crop_w)
        w_layout.addWidget(self.slider_crop_w)
        crop_layout.addLayout(w_layout)

        # Slider Chiều cao
        h_layout = QHBoxLayout()
        self.lbl_crop_h = QLabel("Cao (H):")
        self.lbl_crop_h.setFixedWidth(60)
        self.slider_crop_h = QSlider(Qt.Orientation.Horizontal)
        self.slider_crop_h.setEnabled(False)
        self.slider_crop_h.valueChanged.connect(self.on_crop_slider_moved)
        h_layout.addWidget(self.lbl_crop_h)
        h_layout.addWidget(self.slider_crop_h)
        crop_layout.addLayout(h_layout)

        # Nhãn hiển thị kích thước crop hiện tại
        self.lbl_crop_info = QLabel("Khung cắt: Chưa thiết lập")
        self.lbl_crop_info.setStyleSheet("font-weight: bold; color: #333;")
        crop_layout.addWidget(self.lbl_crop_info)

        left_layout.addWidget(crop_box)

        # --- PHẦN 2: CẮT NGẮN VIDEO (TRIM) ---
        trim_box = QGroupBox("Cắt Ngắn Video (Trim segment)")
        trim_layout = QVBoxLayout(trim_box)
        trim_layout.setSpacing(8)

        # Thanh kéo kép hai đầu trên cùng 1 thanh trượt
        self.slider_trim = QRangeSlider()
        self.slider_trim.setEnabled(False)
        self.slider_trim.rangeChanged.connect(self.on_trim_range_changed)
        trim_layout.addWidget(self.slider_trim)

        # Nhãn hiển thị kết quả đoạn cắt được chọn
        self.lbl_trim_result = QLabel("Đoạn cắt: Chưa chọn")
        self.lbl_trim_result.setStyleSheet("font-weight: bold; color: #2b579a;")
        trim_layout.addWidget(self.lbl_trim_result)

        left_layout.addWidget(trim_box)

        # --- PHẦN 3: THƯ MỤC LƯU ---
        dir_box = QGroupBox("Thư mục lưu kết quả")
        dir_layout = QVBoxLayout(dir_box)
        self.radio_same_edit = QRadioButton("Lưu cùng thư mục gốc (Tự thêm _edited)")
        self.radio_same_edit.setChecked(True)
        self.radio_same_edit.toggled.connect(self.toggle_output_mode_edit)
        
        self.radio_custom_edit = QRadioButton("Lưu thư mục tùy chỉnh:")
        self.radio_custom_edit.toggled.connect(self.toggle_output_mode_edit)

        custom_path_layout = QHBoxLayout()
        self.lbl_custom_path_edit = QLabel("Chưa chọn...")
        self.lbl_custom_path_edit.setStyleSheet("color: #777; padding-left: 20px; font-style: italic;")
        self.btn_select_dir_edit = QPushButton("Chọn thư mục")
        self.btn_select_dir_edit.setEnabled(False)
        self.btn_select_dir_edit.clicked.connect(self.select_custom_directory_edit)
        custom_path_layout.addWidget(self.lbl_custom_path_edit, 1)
        custom_path_layout.addWidget(self.btn_select_dir_edit)

        dir_layout.addWidget(self.radio_same_edit)
        dir_layout.addWidget(self.radio_custom_edit)
        dir_layout.addLayout(custom_path_layout)
        left_layout.addWidget(dir_box)

        # Điều khiển thực thi
        ctrl_layout = QHBoxLayout()
        self.btn_open_dir_edit = QPushButton("Mở thư mục lưu")
        self.btn_open_dir_edit.clicked.connect(self.open_output_directory_edit)
        self.btn_open_dir_edit.setMinimumHeight(35)
        
        self.btn_convert_edit = QPushButton("Cắt & Lưu Video")
        self.btn_convert_edit.clicked.connect(self.start_conversion_edit)
        self.btn_convert_edit.setMinimumHeight(35)
        self.btn_convert_edit.setStyleSheet("""
            QPushButton { background-color: #e81123; color: white; font-weight: bold; border-radius: 5px; padding: 0 20px; }
            QPushButton:hover { background-color: #d11020; }
            QPushButton:pressed { background-color: #a80f1a; }
        """)
        ctrl_layout.addWidget(self.btn_open_dir_edit)
        ctrl_layout.addWidget(self.btn_convert_edit)
        left_layout.addLayout(ctrl_layout)

        # Sử dụng QScrollArea để bao bọc cột điều khiển bên trái, tránh hiện tượng co cụm đè chữ khi độ phân giải màn hình thấp
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setWidget(left_widget)
        scroll_area.setFixedWidth(370)
        
        main_layout.addWidget(scroll_area)

        # --- CỘT PHẢI: MÀN HÌNH XEM TRƯỚC (PREVIEW) ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        lbl_preview_title = QLabel("MÀN HÌNH XEM TRƯỚC VÙNG CẮT")
        lbl_preview_title.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        lbl_preview_title.setStyleSheet("color: #555;")
        right_layout.addWidget(lbl_preview_title)

        self.preview_label = VideoPlayerLabel()
        self.preview_label.cropRectChanged.connect(self.on_mouse_crop_changed)
        
        # Liên kết video sink của media player
        self.video_sink = QVideoSink()
        self.media_player.setVideoOutput(self.video_sink)
        self.video_sink.videoFrameChanged.connect(self.on_video_frame_changed)
        
        right_layout.addWidget(self.preview_label, 1)

        # Thanh Timeline hiển thị tiến trình và tua vị trí phát
        timeline_layout = QHBoxLayout()
        self.lbl_playback_time = QLabel("00:00 / 00:00")
        self.lbl_playback_time.setStyleSheet("font-weight: bold; color: #555;")
        self.slider_playback = QSlider(Qt.Orientation.Horizontal)
        self.slider_playback.setEnabled(False)
        self.slider_playback.sliderMoved.connect(self.on_playback_slider_moved)
        timeline_layout.addWidget(self.lbl_playback_time)
        timeline_layout.addWidget(self.slider_playback)
        right_layout.addLayout(timeline_layout)

        # Thanh điều khiển phát video xem thử (3 nút: Phát/Tiếp tục, Tạm dừng, Dừng)
        play_ctrl_layout = QHBoxLayout()
        play_ctrl_layout.setSpacing(10)
        
        self.btn_play_vid = QPushButton("Phát / Tiếp tục")
        self.btn_play_vid.setEnabled(False)
        self.btn_play_vid.setMinimumHeight(32)
        self.btn_play_vid.setStyleSheet("""
            QPushButton { background-color: #107c41; color: white; font-weight: bold; border-radius: 4px; padding: 6px 15px; }
            QPushButton:hover { background-color: #0b592e; }
            QPushButton:disabled { background-color: #f3f2f1; color: #a19f9d; border: 1px solid #edebe9; }
        """)
        self.btn_play_vid.clicked.connect(self.play_video)
        
        self.btn_pause_vid = QPushButton("Tạm dừng")
        self.btn_pause_vid.setEnabled(False)
        self.btn_pause_vid.setMinimumHeight(32)
        self.btn_pause_vid.setStyleSheet("""
            QPushButton { background-color: #0078d4; color: white; font-weight: bold; border-radius: 4px; padding: 6px 15px; }
            QPushButton:hover { background-color: #106ebe; }
            QPushButton:disabled { background-color: #f3f2f1; color: #a19f9d; border: 1px solid #edebe9; }
        """)
        self.btn_pause_vid.clicked.connect(self.pause_video)
        
        self.btn_stop_vid = QPushButton("Dừng lại (Stop)")
        self.btn_stop_vid.setEnabled(False)
        self.btn_stop_vid.setMinimumHeight(32)
        self.btn_stop_vid.setStyleSheet("""
            QPushButton { background-color: #e81123; color: white; font-weight: bold; border-radius: 4px; padding: 6px 15px; }
            QPushButton:hover { background-color: #d11020; }
            QPushButton:disabled { background-color: #f3f2f1; color: #a19f9d; border: 1px solid #edebe9; }
        """)
        self.btn_stop_vid.clicked.connect(self.stop_video)
        
        play_ctrl_layout.addWidget(self.btn_play_vid)
        play_ctrl_layout.addWidget(self.btn_pause_vid)
        play_ctrl_layout.addWidget(self.btn_stop_vid)
        right_layout.addLayout(play_ctrl_layout)

        main_layout.addWidget(right_widget, 1)

    def handle_file_added_edit(self, paths):
        if not OPENCV_AVAILABLE:
            return
            
        if len(paths) == 1 and paths[0] == "__SELECT_FILES__":
            file_dialog = QFileDialog()
            selected_files, _ = file_dialog.getOpenFileNames(
                self, "Chọn một video để cắt chỉnh sửa", "",
                "Video (*.mp4 *.mkv *.avi *.mov *.webm *.flv *.wmv);;Tất cả (*.*)"
            )
            paths = selected_files
            if not paths:
                return

        # Chỉ lấy tệp tin video đầu tiên
        target_file = None
        SUPPORTED_VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv")
        for path in paths:
            if os.path.isfile(path) and path.lower().endswith(SUPPORTED_VIDEO_EXTS):
                target_file = os.path.abspath(path)
                break

        if not target_file:
            QMessageBox.warning(self, "Định dạng sai", "Vui lòng chọn một tệp tin video hợp lệ.")
            return

        # Giải phóng tệp video trước đó nếu có
        if self.cap:
            self.cap.release()
            self.cap = None

        self.file_path_edit = target_file
        
        # Mở video bằng OpenCV
        self.cap = cv2.VideoCapture(self.file_path_edit)
        if not self.cap.isOpened():
            QMessageBox.critical(self, "Lỗi mở file", "Không thể mở video bằng thư viện OpenCV.")
            self.file_path_edit = ""
            return

        # Đọc thông số metadata của video
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        if self.fps <= 0:
            self.fps = 30.0
            
        self.video_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.video_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.duration = self.total_frames / self.fps

        info_text = (
            f"Tên file: {os.path.basename(self.file_path_edit)}\n"
            f"Kích thước gốc: {self.video_width} x {self.video_height} pixels\n"
            f"Thời lượng: {self.format_time_sec(self.duration)} ({self.total_frames} khung hình) @ {self.fps:.2f} fps"
        )
        self.lbl_video_info.setText(info_text)

        # Cấu hình thanh trượt Crop
        self.block_crop_signals(True)
        try:
            self.slider_crop_x.setRange(0, self.video_width - 10)
            self.slider_crop_y.setRange(0, self.video_height - 10)
            self.slider_crop_w.setRange(10, self.video_width)
            self.slider_crop_h.setRange(10, self.video_height)
            
            # Khởi tạo mặc định lấy toàn bộ khung hình
            self.slider_crop_w.setValue(self.video_width)
            self.slider_crop_h.setValue(self.video_height)
            self.slider_crop_x.setValue(0)
            self.slider_crop_y.setValue(0)
            
            self.slider_crop_x.setEnabled(True)
            self.slider_crop_y.setEnabled(True)
            self.slider_crop_w.setEnabled(True)
            self.slider_crop_h.setEnabled(True)
        finally:
            self.block_crop_signals(False)

        # Cấu hình thanh trượt Trim và các nút phát video
        self.stop_video()
        
        # Nạp tệp tin vào QMediaPlayer
        self.media_player.setSource(QUrl.fromLocalFile(self.file_path_edit))
        
        self.trim_start_frame = 0
        self.trim_end_frame = self.total_frames - 1
        
        self.slider_trim.blockSignals(True)
        try:
            self.slider_trim.setRange(0, self.total_frames - 1)
            self.slider_trim.setValues(0, self.total_frames - 1)
            self.slider_trim.setEnabled(True)
        finally:
            self.slider_trim.blockSignals(False)

        # Cấu hình timeline phát
        self.slider_playback.blockSignals(True)
        self.slider_playback.setRange(0, int(self.duration * 1000))
        self.slider_playback.setValue(0)
        self.slider_playback.setEnabled(True)
        self.slider_playback.blockSignals(False)
        self.lbl_playback_time.setText(f"00:00.00 / {self.format_time_sec(self.duration)}")

        self.btn_play_vid.setEnabled(True)
        self.btn_pause_vid.setEnabled(True)
        self.btn_stop_vid.setEnabled(True)
        
        # Thiết lập kích thước vẽ khung Crop
        self.preview_label.set_media_size(self.video_width, self.video_height)
        
        self.update_trim_result_label()

        self.on_crop_ratio_changed()
        self.show_frame(0)

    def show_frame(self, frame_number):
        if not self.cap or not self.cap.isOpened():
            return
        pos_ms = int(frame_number / self.fps * 1000)
        self.media_player.setPosition(pos_ms)

    def on_crop_slider_moved(self):
        if not self.cap or not self.cap.isOpened():
            return
            
        self.block_crop_signals(True)
        try:
            w = self.slider_crop_w.value()
            h = self.slider_crop_h.value()
            x = self.slider_crop_x.value()
            y = self.slider_crop_y.value()
            
            ratio = self.get_current_aspect_ratio()
            if ratio:
                # Nếu tỷ lệ cố định, tự động tính Height theo Width
                h = int(w / ratio)
                if h > self.video_height:
                    h = self.video_height
                    w = int(h * ratio)
                    self.slider_crop_w.setValue(w)
                self.slider_crop_h.setValue(h)
                
            # Đảm bảo khung crop không trượt ra ngoài rìa video
            if x + w > self.video_width:
                x = self.video_width - w
                self.slider_crop_x.setValue(x)
                
            if y + h > self.video_height:
                y = self.video_height - h
                self.slider_crop_y.setValue(y)
                
            self.preview_label.set_crop_rect(x, y, w, h)
            self.lbl_crop_info.setText(f"Khung cắt: {w}x{h} tại điểm ({x}, {y})")
        finally:
            self.block_crop_signals(False)

    def on_crop_ratio_changed(self):
        if not self.cap or not self.cap.isOpened():
            return
            
        ratio = self.get_current_aspect_ratio()
        self.preview_label.set_aspect_ratio(ratio)
        
        if ratio:
            # Tự động vô hiệu hóa thanh trượt chiều cao khi khóa tỉ lệ cố định
            self.slider_crop_h.setEnabled(False)
            w = self.slider_crop_w.value()
            h = int(w / ratio)
            if h > self.video_height:
                h = self.video_height
                w = int(h * ratio)
                self.slider_crop_w.setValue(w)
            self.slider_crop_h.setValue(h)
        else:
            self.slider_crop_h.setEnabled(True)
            
        self.on_crop_slider_moved()

    def on_mouse_crop_changed(self, x, y, w, h):
        if not self.cap or not self.cap.isOpened():
            return
        if self.is_playing:
            self.stop_video()
        self.block_crop_signals(True)
        try:
            self.slider_crop_x.setValue(x)
            self.slider_crop_y.setValue(y)
            self.slider_crop_w.setValue(w)
            self.slider_crop_h.setValue(h)
            self.lbl_crop_info.setText(f"Khung cắt: {w}x{h} tại điểm ({x}, {y})")
        finally:
            self.block_crop_signals(False)

    def get_current_aspect_ratio(self):
        text = self.combo_crop_ratio.currentText()
        if "16:9" in text:
            return 16.0 / 9.0
        elif "9:16" in text:
            return 9.0 / 16.0
        elif "1:1" in text:
            return 1.0
        elif "4:3" in text:
            return 4.0 / 3.0
        return None

    def on_trim_range_changed(self, start, end):
        if not self.cap or not self.cap.isOpened():
            return
            
        if self.is_playing:
            self.pause_video()
            
        start_ms = int(start / self.fps * 1000)
        end_ms = int(end / self.fps * 1000)
        
        if start != self.trim_start_frame:
            self.media_player.setPosition(start_ms)
        elif end != self.trim_end_frame:
            self.media_player.setPosition(end_ms)
            
        self.trim_start_frame = start
        self.trim_end_frame = end
        self.update_trim_result_label()

    def play_video(self):
        if not self.cap or not self.cap.isOpened():
            return
        self.media_player.play()
        self.is_playing = True

    def pause_video(self):
        self.media_player.pause()
        self.is_playing = False

    def stop_video(self):
        self.media_player.stop()
        self.is_playing = False
        start_ms = int(self.trim_start_frame / self.fps * 1000)
        self.media_player.setPosition(start_ms)

    def on_playback_slider_moved(self, position_ms):
        self.media_player.setPosition(position_ms)

    def on_player_position_changed(self, pos_ms):
        self.slider_playback.blockSignals(True)
        self.slider_playback.setValue(pos_ms)
        self.slider_playback.blockSignals(False)
        
        self.lbl_playback_time.setText(
            f"{self.format_time_sec(pos_ms / 1000.0)} / {self.format_time_sec(self.duration)}"
        )
        
        start_ms = int(self.trim_start_frame / self.fps * 1000)
        end_ms = int(self.trim_end_frame / self.fps * 1000)
        
        if pos_ms >= end_ms:
            self.media_player.setPosition(start_ms)
        elif pos_ms < start_ms:
            self.media_player.setPosition(start_ms)

    def on_player_duration_changed(self, duration_ms):
        if duration_ms > 0:
            self.slider_playback.setRange(0, duration_ms)

    def on_video_frame_changed(self, frame):
        if frame.isValid():
            image = frame.toImage()
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)
                self.preview_label.set_pixmap(pixmap)

    def update_trim_result_label(self):
        t_start = self.trim_start_frame / self.fps
        t_end = self.trim_end_frame / self.fps
        dur = t_end - t_start
        self.lbl_trim_result.setText(
            f"Đoạn cắt: {self.format_time_sec(t_start)} ---> {self.format_time_sec(t_end)} (Thời lượng: {dur:.2f}s)"
        )

    def format_time_sec(self, seconds):
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        csecs = int((seconds * 100) % 100)
        return f"{mins:02d}:{secs:02d}.{csecs:02d}"

    def block_crop_signals(self, block):
        self.slider_crop_x.blockSignals(block)
        self.slider_crop_y.blockSignals(block)
        self.slider_crop_w.blockSignals(block)
        self.slider_crop_h.blockSignals(block)

    def toggle_output_mode_edit(self):
        is_custom = self.radio_custom_edit.isChecked()
        self.btn_select_dir_edit.setEnabled(is_custom)
        if is_custom and not self.custom_output_dir_edit:
            self.select_custom_directory_edit()

    def select_custom_directory_edit(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Chọn thư mục đầu ra")
        if dir_path:
            self.custom_output_dir_edit = os.path.abspath(dir_path)
            self.lbl_custom_path_edit.setText(self.custom_output_dir_edit)
            self.lbl_custom_path_edit.setStyleSheet("color: #000; padding-left: 20px; font-weight: bold;")
        else:
            if not self.custom_output_dir_edit:
                self.radio_same_edit.setChecked(True)

    def open_output_directory_edit(self):
        if self.radio_custom_edit.isChecked() and self.custom_output_dir_edit:
            path = self.custom_output_dir_edit
        elif self.file_path_edit:
            path = os.path.dirname(self.file_path_edit)
        else:
            path = os.path.abspath(".")
            
        if os.path.exists(path):
            os.startfile(path)
        else:
            QMessageBox.warning(self, "Không tìm thấy", f"Thư mục không tồn tại: {path}")

    def start_conversion_edit(self):
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        ffmpeg_path = os.path.join(base_dir, "ffmpeg", "ffmpeg.exe")
        
        if not os.path.exists(ffmpeg_path):
            QMessageBox.critical(
                self, "Không tìm thấy FFmpeg",
                "Vui lòng copy tệp 'ffmpeg.exe' vào thư mục 'ffmpeg/' để cắt video."
            )
            return

        if not self.file_path_edit:
            QMessageBox.warning(self, "Chưa nạp video", "Vui lòng kéo thả hoặc nạp tệp video trước.")
            return

        if self.radio_custom_edit.isChecked() and not self.custom_output_dir_edit:
            QMessageBox.warning(self, "Chưa chọn thư mục", "Vui lòng chọn thư mục lưu trước.")
            return

        # Tính toán thời gian và tọa độ cắt
        start_sec = self.trim_start_frame / self.fps
        end_sec = self.trim_end_frame / self.fps
        
        x = self.slider_crop_x.value()
        y = self.slider_crop_y.value()
        w = self.slider_crop_w.value()
        h = self.slider_crop_h.value()
        crop_rect = (x, y, w, h)

        # Tính toán đường dẫn xuất
        base_dir_in = os.path.dirname(self.file_path_edit)
        ext = os.path.splitext(self.file_path_edit)[1].lower()
        orig_name = os.path.splitext(os.path.basename(self.file_path_edit))[0]
        
        if self.radio_same_edit.isChecked():
            out_dir = base_dir_in
            out_path = os.path.join(out_dir, f"{orig_name}_edited{ext}")
        else:
            out_dir = self.custom_output_dir_edit
            out_path = os.path.join(out_dir, f"{orig_name}_edited{ext}")

        # Khóa giao diện khi đang xử lý
        self.stop_video()
        self.btn_convert_edit.setEnabled(False)
        self.btn_convert_edit.setText("Đang cắt...")
        self.drop_zone_edit.setEnabled(False)
        self.combo_crop_ratio.setEnabled(False)
        self.slider_crop_x.setEnabled(False)
        self.slider_crop_y.setEnabled(False)
        self.slider_crop_w.setEnabled(False)
        self.slider_crop_h.setEnabled(False)
        self.slider_trim.setEnabled(False)
        self.slider_playback.setEnabled(False)
        self.btn_play_vid.setEnabled(False)
        self.btn_pause_vid.setEnabled(False)
        self.btn_stop_vid.setEnabled(False)
        self.radio_same_edit.setEnabled(False)
        self.radio_custom_edit.setEnabled(False)
        self.btn_select_dir_edit.setEnabled(False)

        # Khởi chạy luồng nén và cắt video
        self.worker_edit = VideoEditWorker(
            ffmpeg_path=ffmpeg_path,
            input_path=self.file_path_edit,
            out_path=out_path,
            start_time=start_sec,
            end_time=end_sec,
            crop_rect=crop_rect,
            video_width=self.video_width,
            video_height=self.video_height
        )
        self.worker_edit.finished.connect(self.handle_edit_finished)
        self.worker_edit.start()

    def handle_edit_finished(self, success, message):
        # Mở khóa giao diện
        self.btn_convert_edit.setEnabled(True)
        self.btn_convert_edit.setText("Cắt & Lưu Video")
        self.drop_zone_edit.setEnabled(True)
        self.combo_crop_ratio.setEnabled(True)
        self.slider_crop_x.setEnabled(True)
        self.slider_crop_y.setEnabled(True)
        self.slider_crop_w.setEnabled(True)
        
        ratio = self.get_current_aspect_ratio()
        if not ratio:
            self.slider_crop_h.setEnabled(True)
            
        self.slider_trim.setEnabled(True)
        self.slider_playback.setEnabled(True)
        self.btn_play_vid.setEnabled(True)
        self.btn_pause_vid.setEnabled(True)
        self.btn_stop_vid.setEnabled(True)
        self.radio_same_edit.setEnabled(True)
        self.radio_custom_edit.setEnabled(True)
        if self.radio_custom_edit.isChecked():
            self.btn_select_dir_edit.setEnabled(True)

        if success:
            QMessageBox.information(self, "Hoàn tất", f"Video đã được cắt và lưu thành công!\n\n{message}")
        else:
            QMessageBox.critical(self, "Lỗi cắt video", f"Quá trình cắt video thất bại.\nChi tiết:\n{message}")

    # --- CÁC HÀM TIỆN ÍCH KHÁC (Tab 1 & 2) ---
    def toggle_output_mode_img(self):
        is_custom = self.radio_custom_img.isChecked()
        self.btn_select_dir_img.setEnabled(is_custom)
        if is_custom and not self.custom_output_dir_img:
            self.select_custom_directory_img()

    def select_custom_directory_img(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Chọn thư mục đầu ra")
        if dir_path:
            self.custom_output_dir_img = os.path.abspath(dir_path)
            self.lbl_custom_path_img.setText(self.custom_output_dir_img)
            self.lbl_custom_path_img.setStyleSheet("color: #000; padding-left: 20px; font-weight: bold;")
        else:
            if not self.custom_output_dir_img:
                self.radio_same_img.setChecked(True)

    def toggle_output_mode_vid(self):
        is_custom = self.radio_custom_vid.isChecked()
        self.btn_select_dir_vid.setEnabled(is_custom)
        if is_custom and not self.custom_output_dir_vid:
            self.select_custom_directory_vid()

    def select_custom_directory_vid(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Chọn thư mục đầu ra")
        if dir_path:
            self.custom_output_dir_vid = os.path.abspath(dir_path)
            self.lbl_custom_path_vid.setText(self.custom_output_dir_vid)
            self.lbl_custom_path_vid.setStyleSheet("color: #000; padding-left: 20px; font-weight: bold;")
        else:
            if not self.custom_output_dir_vid:
                self.radio_same_vid.setChecked(True)

    def update_quality_label(self, val):
        if val >= 90:
            self.lbl_quality_val_img.setText(f"{val}% (Chất lượng cao)")
        elif val >= 75:
            self.lbl_quality_val_img.setText(f"{val}% (Khuyên dùng)")
        else:
            self.lbl_quality_val_img.setText(f"{val}% (Tiết kiệm dung lượng)")

    def handle_format_changed_img(self, text):
        fmt = text.split(" ")[0].lower()
        if fmt in ("jpeg", "webp"):
            self.quality_group_img.setVisible(True)
            if fmt == "jpeg":
                self.quality_group_img.setTitle("Chất lượng JPEG đầu ra")
            else:
                self.quality_group_img.setTitle("Chất lượng WebP đầu ra")
            self.update_quality_label(self.slider_quality_img.value())
        else:
            self.quality_group_img.setVisible(False)

    def handle_format_changed_vid(self, text):
        fmt = text.split(" ")[0].lower()
        if fmt in ("mp4", "webm", "mkv", "avi"):
            self.video_quality_group.setVisible(True)
        else:
            self.video_quality_group.setVisible(False)

    def open_output_directory_img(self):
        if self.radio_custom_img.isChecked() and self.custom_output_dir_img:
            path = self.custom_output_dir_img
        elif self.file_list_img:
            path = os.path.dirname(self.file_list_img[0])
        else:
            path = os.path.abspath(".")
            
        if os.path.exists(path):
            os.startfile(path)
        else:
            QMessageBox.warning(self, "Không tìm thấy", f"Thư mục không tồn tại: {path}")

    def open_output_directory_vid(self):
        if self.radio_custom_vid.isChecked() and self.custom_output_dir_vid:
            path = self.custom_output_dir_vid
        elif self.file_list_vid:
            path = os.path.dirname(self.file_list_vid[0])
        else:
            path = os.path.abspath(".")
            
        if os.path.exists(path):
            os.startfile(path)
        else:
            QMessageBox.warning(self, "Không tìm thấy", f"Thư mục không tồn tại: {path}")

    def clear_list_img(self):
        self.file_list_img.clear()
        self.file_row_map_img.clear()
        self.table_img.setRowCount(0)
        self.progress_bar_img.setVisible(False)
        self.lbl_status_img.setText("Đã xóa danh sách ảnh. Chưa có ảnh nào được thêm vào.")

    def clear_list_vid(self):
        self.file_list_vid.clear()
        self.file_row_map_vid.clear()
        self.table_vid.setRowCount(0)
        self.progress_bar_vid.setVisible(False)
        self.lbl_status_vid.setText("Đã xóa danh sách video. Chưa có video nào được thêm vào.")

    def handle_files_added_img(self, paths):
        SUPPORTED_IMAGE_EXTS = (".jxl", ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff")
        
        if len(paths) == 1 and paths[0] == "__SELECT_FILES__":
            file_dialog = QFileDialog()
            selected_files, _ = file_dialog.getOpenFileNames(
                self, "Chọn các tệp tin ảnh", "",
                "Ảnh (*.jxl *.jpg *.jpeg *.png *.webp *.bmp *.tiff);;Tất cả (*.*)"
            )
            paths = selected_files
            if not paths:
                return

        valid_files = []
        for path in paths:
            if os.path.isfile(path):
                if path.lower().endswith(SUPPORTED_IMAGE_EXTS):
                    valid_files.append(os.path.abspath(path))
            elif os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for file in files:
                        if file.lower().endswith(SUPPORTED_IMAGE_EXTS):
                            valid_files.append(os.path.abspath(os.path.join(root, file)))

        if not valid_files:
            return

        new_added = 0
        self.table_img.setUpdatesEnabled(False)
        try:
            for idx, file in enumerate(valid_files):
                if file not in self.file_row_map_img:
                    row = self.table_img.rowCount()
                    self.file_row_map_img[file] = row
                    self.file_list_img.append(file)
                    new_added += 1
                    
                    self.table_img.insertRow(row)
                    self.table_img.setItem(row, 0, QTableWidgetItem(os.path.basename(file)))
                    self.table_img.setItem(row, 1, QTableWidgetItem(file))
                    
                    sz_bytes = os.path.getsize(file)
                    item_sz = QTableWidgetItem(self.format_size(sz_bytes))
                    item_sz.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.table_img.setItem(row, 2, item_sz)
                    
                    item_status = QTableWidgetItem("Chờ chuyển đổi")
                    item_status.setForeground(QColor("#777777"))
                    self.table_img.setItem(row, 3, item_status)
                    
                    if new_added % 50 == 0:
                        QCoreApplication.processEvents()
        finally:
            self.table_img.setUpdatesEnabled(True)

        self.lbl_status_img.setText(f"Đã thêm mới {new_added} ảnh. Tổng cộng: {len(self.file_list_img)} ảnh.")

    def handle_files_added_vid(self, paths):
        SUPPORTED_VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv")
        
        if len(paths) == 1 and paths[0] == "__SELECT_FILES__":
            file_dialog = QFileDialog()
            selected_files, _ = file_dialog.getOpenFileNames(
                self, "Chọn các tệp tin video", "",
                "Video (*.mp4 *.mkv *.avi *.mov *.webm *.flv *.wmv);;Tất cả (*.*)"
            )
            paths = selected_files
            if not paths:
                return

        valid_files = []
        for path in paths:
            if os.path.isfile(path):
                if path.lower().endswith(SUPPORTED_VIDEO_EXTS):
                    valid_files.append(os.path.abspath(path))
            elif os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for file in files:
                        if file.lower().endswith(SUPPORTED_VIDEO_EXTS):
                            valid_files.append(os.path.abspath(os.path.join(root, file)))

        if not valid_files:
            return

        new_added = 0
        self.table_vid.setUpdatesEnabled(False)
        try:
            for idx, file in enumerate(valid_files):
                if file not in self.file_row_map_vid:
                    row = self.table_vid.rowCount()
                    self.file_row_map_vid[file] = row
                    self.file_list_vid.append(file)
                    new_added += 1
                    
                    self.table_vid.insertRow(row)
                    self.table_vid.setItem(row, 0, QTableWidgetItem(os.path.basename(file)))
                    self.table_vid.setItem(row, 1, QTableWidgetItem(file))
                    
                    sz_bytes = os.path.getsize(file)
                    item_sz = QTableWidgetItem(self.format_size(sz_bytes))
                    item_sz.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.table_vid.setItem(row, 2, item_sz)
                    
                    item_status = QTableWidgetItem("Chờ chuyển đổi")
                    item_status.setForeground(QColor("#777777"))
                    self.table_vid.setItem(row, 3, item_status)
                    
                    if new_added % 50 == 0:
                        QCoreApplication.processEvents()
        finally:
            self.table_vid.setUpdatesEnabled(True)

        self.lbl_status_vid.setText(f"Đã thêm mới {new_added} video. Tổng cộng: {len(self.file_list_vid)} video.")

    def format_size(self, size_in_bytes):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_in_bytes < 1024.0:
                return f"{size_in_bytes:.1f} {unit}"
            size_in_bytes /= 1024.0
        return f"{size_in_bytes:.1f} TB"

    def start_conversion_img(self):
        if not self.file_list_img:
            QMessageBox.warning(self, "Không có tệp", "Vui lòng kéo thả hoặc chọn ảnh trước.")
            return

        if self.radio_custom_img.isChecked() and not self.custom_output_dir_img:
            QMessageBox.warning(self, "Chưa chọn thư mục", "Vui lòng chọn thư mục lưu kết quả trước.")
            return

        # Đổi hành vi nút chuyển đổi sang nút Hủy
        self.btn_convert_img.setText("Hủy bỏ")
        self.btn_convert_img.setStyleSheet("""
            QPushButton { background-color: #d83b01; color: white; font-weight: bold; border-radius: 5px; padding: 0 20px; }
            QPushButton:hover { background-color: #b83200; }
        """)
        self.btn_convert_img.clicked.disconnect(self.start_conversion_img)
        self.btn_convert_img.clicked.connect(self.cancel_conversion_img)

        # Khóa giao diện khác
        self.btn_clear_img.setEnabled(False)
        self.btn_open_dir_img.setEnabled(False)
        self.drop_zone_img.setEnabled(False)
        self.combo_format_img.setEnabled(False)
        self.slider_quality_img.setEnabled(False)
        self.radio_same_img.setEnabled(False)
        self.radio_custom_img.setEnabled(False)
        self.btn_select_dir_img.setEnabled(False)
        self.txt_prefix_img.setEnabled(False)
        self.txt_suffix_img.setEnabled(False)
        
        self.progress_bar_img.setVisible(True)
        self.progress_bar_img.setRange(0, len(self.file_list_img))
        self.progress_bar_img.setValue(0)
        
        self.table_img.setUpdatesEnabled(False)
        try:
            for row in range(self.table_img.rowCount()):
                item = self.table_img.item(row, 3)
                if item:
                    item.setText("Đang chờ...")
                    item.setForeground(QColor("#777777"))
        finally:
            self.table_img.setUpdatesEnabled(True)

        target_format = self.combo_format_img.currentText().split(" ")[0]
        prefix = self.txt_prefix_img.text().strip()
        suffix = self.txt_suffix_img.text().strip()

        self.worker_img = ConversionWorker(
            files=self.file_list_img,
            output_dir_mode="same" if self.radio_same_img.isChecked() else "custom",
            custom_output_dir=self.custom_output_dir_img,
            target_format=target_format,
            quality=self.slider_quality_img.value(),
            prefix=prefix,
            suffix=suffix
        )
        self.worker_img.file_processed.connect(self.handle_file_processed_img)
        self.worker_img.overall_progress.connect(self.progress_bar_img.setValue)
        self.worker_img.finished.connect(self.handle_conversion_finished_img)
        self.worker_img.start()

    def cancel_conversion_img(self):
        if self.worker_img and self.worker_img.isRunning():
            self.worker_img.stop()
            self.lbl_status_img.setText("Đang dừng tiến trình chuyển đổi ảnh...")
            self.btn_convert_img.setEnabled(False)

    def handle_file_processed_img(self, file_path, status, message):
        row = self.file_row_map_img.get(file_path)
        if row is not None:
            status_item = self.table_img.item(row, 3)
            if status_item:
                status_item.setText(status)
                if status == "Thành công":
                    status_item.setForeground(QColor("#227a22"))
                    status_item.setToolTip(message)
                else:
                    status_item.setForeground(QColor("#cc0000"))
                    status_item.setToolTip(message)
                
                curr_time = time.time()
                if curr_time - self.last_scroll_time_img > 0.1:
                    self.table_img.scrollToItem(status_item)
                    self.last_scroll_time_img = curr_time

    def handle_conversion_finished_img(self):
        self.btn_convert_img.setEnabled(True)
        self.btn_convert_img.setText("Bắt đầu chuyển đổi")
        self.btn_convert_img.setStyleSheet("""
            QPushButton { background-color: #0078d4; color: white; font-weight: bold; border-radius: 5px; padding: 0 20px; }
            QPushButton:hover { background-color: #106ebe; }
            QPushButton:pressed { background-color: #005a9e; }
        """)
        self.btn_convert_img.clicked.disconnect(self.cancel_conversion_img)
        self.btn_convert_img.clicked.connect(self.start_conversion_img)

        self.btn_clear_img.setEnabled(True)
        self.btn_open_dir_img.setEnabled(True)
        self.drop_zone_img.setEnabled(True)
        self.combo_format_img.setEnabled(True)
        if self.combo_format_img.currentText().split(" ")[0].lower() in ("jpeg", "webp"):
            self.slider_quality_img.setEnabled(True)
        self.radio_same_img.setEnabled(True)
        self.radio_custom_img.setEnabled(True)
        if self.radio_custom_img.isChecked():
            self.btn_select_dir_img.setEnabled(True)
        self.txt_prefix_img.setEnabled(True)
        self.txt_suffix_img.setEnabled(True)

        self.lbl_status_img.setText(f"Hoàn tất xử lý ảnh. Tổng cộng: {len(self.file_list_img)} ảnh.")

    def start_conversion_vid(self):
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        ffmpeg_path = os.path.join(base_dir, "ffmpeg", "ffmpeg.exe")
        
        if not os.path.exists(ffmpeg_path):
            QMessageBox.critical(
                self,
                "Không tìm thấy FFmpeg",
                "Vui lòng copy tệp 'ffmpeg.exe' vào thư mục 'ffmpeg/' để thực hiện chuyển đổi Video / MP3."
            )
            return

        if not self.file_list_vid:
            QMessageBox.warning(self, "Không có tệp", "Vui lòng kéo thả hoặc chọn video trước.")
            return

        if self.radio_custom_vid.isChecked() and not self.custom_output_dir_vid:
            QMessageBox.warning(self, "Chưa chọn thư mục", "Vui lòng chọn thư mục lưu kết quả trước.")
            return

        self.btn_convert_vid.setText("Hủy bỏ")
        self.btn_convert_vid.setStyleSheet("""
            QPushButton { background-color: #d83b01; color: white; font-weight: bold; border-radius: 5px; padding: 0 20px; }
            QPushButton:hover { background-color: #b83200; }
        """)
        self.btn_convert_vid.clicked.disconnect(self.start_conversion_vid)
        self.btn_convert_vid.clicked.connect(self.cancel_conversion_vid)

        self.btn_clear_vid.setEnabled(False)
        self.btn_open_dir_vid.setEnabled(False)
        self.drop_zone_vid.setEnabled(False)
        self.combo_format_vid.setEnabled(False)
        self.combo_video_quality.setEnabled(False)
        self.radio_same_vid.setEnabled(False)
        self.radio_custom_vid.setEnabled(False)
        self.btn_select_dir_vid.setEnabled(False)
        self.txt_prefix_vid.setEnabled(False)
        self.txt_suffix_vid.setEnabled(False)
        
        self.progress_bar_vid.setVisible(True)
        self.progress_bar_vid.setRange(0, len(self.file_list_vid))
        self.progress_bar_vid.setValue(0)
        
        self.table_vid.setUpdatesEnabled(False)
        try:
            for row in range(self.table_vid.rowCount()):
                item = self.table_vid.item(row, 3)
                if item:
                    item.setText("Đang chờ...")
                    item.setForeground(QColor("#777777"))
        finally:
            self.table_vid.setUpdatesEnabled(True)

        target_format = self.combo_format_vid.currentText().split(" ")[0]
        
        crf_text = self.combo_video_quality.currentText()
        if "Cao" in crf_text:
            crf_val = 18
        elif "Thấp" in crf_text:
            crf_val = 28
        else:
            crf_val = 23
            
        prefix = self.txt_prefix_vid.text().strip()
        suffix = self.txt_suffix_vid.text().strip()

        self.worker_vid = ConversionWorker(
            files=self.file_list_vid,
            output_dir_mode="same" if self.radio_same_vid.isChecked() else "custom",
            custom_output_dir=self.custom_output_dir_vid,
            target_format=target_format,
            quality=90,
            video_crf=crf_val,
            prefix=prefix,
            suffix=suffix
        )
        self.worker_vid.file_processed.connect(self.handle_file_processed_vid)
        self.worker_vid.overall_progress.connect(self.progress_bar_vid.setValue)
        self.worker_vid.finished.connect(self.handle_conversion_finished_vid)
        self.worker_vid.start()

    def cancel_conversion_vid(self):
        if self.worker_vid and self.worker_vid.isRunning():
            self.worker_vid.stop()
            self.lbl_status_vid.setText("Đang dừng tiến trình chuyển đổi video...")
            self.btn_convert_vid.setEnabled(False)

    def handle_file_processed_vid(self, file_path, status, message):
        row = self.file_row_map_vid.get(file_path)
        if row is not None:
            status_item = self.table_vid.item(row, 3)
            if status_item:
                status_item.setText(status)
                if status == "Thành công":
                    status_item.setForeground(QColor("#227a22"))
                    status_item.setToolTip(message)
                else:
                    status_item.setForeground(QColor("#cc0000"))
                    status_item.setToolTip(message)
                
                curr_time = time.time()
                if curr_time - self.last_scroll_time_vid > 0.1:
                    self.table_vid.scrollToItem(status_item)
                    self.last_scroll_time_vid = curr_time

    def handle_conversion_finished_vid(self):
        self.btn_convert_vid.setEnabled(True)
        self.btn_convert_vid.setText("Bắt đầu chuyển đổi")
        self.btn_convert_vid.setStyleSheet("""
            QPushButton { background-color: #228b22; color: white; font-weight: bold; border-radius: 5px; padding: 0 20px; }
            QPushButton:hover { background-color: #1e781e; }
            QPushButton:pressed { background-color: #145014; }
        """)
        self.btn_convert_vid.clicked.disconnect(self.cancel_conversion_vid)
        self.btn_convert_vid.clicked.connect(self.start_conversion_vid)

        self.btn_clear_vid.setEnabled(True)
        self.btn_open_dir_vid.setEnabled(True)
        self.drop_zone_vid.setEnabled(True)
        self.combo_format_vid.setEnabled(True)
        self.combo_video_quality.setEnabled(True)
        self.radio_same_vid.setEnabled(True)
        self.radio_custom_vid.setEnabled(True)
        if self.radio_custom_vid.isChecked():
            self.btn_select_dir_vid.setEnabled(True)
        self.txt_prefix_vid.setEnabled(True)
        self.txt_suffix_vid.setEnabled(True)

        self.lbl_status_vid.setText(f"Hoàn tất xử lý video. Tổng cộng: {len(self.file_list_vid)} tệp.")

    def check_jxl_support(self):
        if not JXL_SUPPORTED:
            QMessageBox.warning(
                self,
                "Thiếu hỗ trợ định dạng JPEG XL",
                "Lưu ý: Thư viện giải mã JPEG XL (.jxl) chưa được tải.\n\n"
                "Bạn vẫn có thể chuyển đổi qua lại giữa các định dạng khác (JPG, PNG, WebP, BMP, TIFF).\n"
                "Nếu muốn xử lý thêm file .jxl, vui lòng chạy phần mềm bằng tệp 'run.bat' để tự động cấu hình môi trường."
            )

    # Đảm bảo tắt kết nối camera và tệp tin khi đóng ứng dụng
    def closeEvent(self, event):
        self.media_player.stop()
        if self.cap:
            self.cap.release()
            self.cap = None
        event.accept()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
