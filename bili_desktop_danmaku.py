import sys
import asyncio
import threading
import random
import json
import os
from collections import deque  # <--- 引入双端队列用于排队
from PyQt5.QtWidgets import (QApplication, QWidget, QSystemTrayIcon, QMenu, 
                             QAction, QStyle, QSizeGrip, QDialog, QFormLayout, 
                             QSpinBox, QDoubleSpinBox, QSlider, QLabel, QHBoxLayout, 
                             QLineEdit, QPushButton, QMessageBox, QVBoxLayout)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPainter, QFont, QColor, QFontMetrics, QPainterPath, QPen, QPixmap
from bilibili_api import live

# ================= 配置文件管理 =================
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "room_ids": [26722888, 42062], 
    "font_size": 18,
    "line_limit": 0,
    "speed_base": 2.7,
    "outline_width": 1.2,
    "opacity": 137
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return DEFAULT_CONFIG

def save_config(config_data):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)
    except Exception as e:
        print(f"保存配置失败: {e}")

# ================= 直播监听控制器 =================
class LiveMonitor:
    def __init__(self, signal):
        self.signal = signal
        self.loop = None
        self.stop_event = None
        self.thread = None

    def start(self, room_ids):
        self.stop()
        if not room_ids:
            return
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run_loop, args=(room_ids,), daemon=True)
        self.thread.start()

    def stop(self):
        if self.loop and self.loop.is_running():
            for task in asyncio.all_tasks(self.loop):
                self.loop.call_soon_threadsafe(task.cancel)
        
    def _run_loop(self, room_ids):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        tasks = []
        clients = []
        print(f"正在连接直播间: {room_ids}")

        for room_id in room_ids:
            try:
                rid = int(room_id)
                client = live.LiveDanmaku(rid)
                
                @client.on('DANMU_MSG')
                async def on_danmaku(event, r_id=rid):
                    try:
                        content = event['data']['info'][1]
                        self.signal.emit(content)
                    except:
                        pass
                
                clients.append(client)
                tasks.append(client.connect())
            except ValueError:
                print(f"无效的房间ID: {room_id}")

        if not tasks:
            return

        async def main_entry():
            try:
                await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                pass

        try:
            self.loop.run_until_complete(main_entry())
        except Exception as e:
            print(f"监听循环出错: {e}")

# ================= 弹幕设置窗口 =================
class SettingsDialog(QDialog):
    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.setWindowTitle("⚙️ 弹幕配置")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.resize(350, 350)
        self.initUI()

    def initUI(self):
        main_layout = QVBoxLayout()
        form_layout = QFormLayout()
        
        self.room_edit = QLineEdit()
        current_rooms = ",".join(map(str, self.parent_window.room_ids))
        self.room_edit.setText(current_rooms)
        self.room_edit.setPlaceholderText("例如: 123, 456")
        form_layout.addRow("🔴 直播间 ID:", self.room_edit)
        
        self.font_spin = QSpinBox()
        self.font_spin.setRange(10, 120)
        self.font_spin.setValue(self.parent_window.font_size)
        self.font_spin.valueChanged.connect(self.parent_window.set_font_size)
        form_layout.addRow("🔠 字体大小 (px):", self.font_spin)

        self.line_spin = QSpinBox()
        self.line_spin.setRange(0, 50)
        self.line_spin.setSpecialValueText("自动 (填满)")
        self.line_spin.setValue(self.parent_window.line_limit)
        self.line_spin.valueChanged.connect(self.parent_window.set_line_limit)
        form_layout.addRow("🔢 显示行数:", self.line_spin)
        
        speed_layout = QHBoxLayout()
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(10, 150)
        self.speed_slider.setValue(int(self.parent_window.speed_base * 10))
        self.speed_label = QLabel(f"{self.parent_window.speed_base}")
        
        def on_speed_change(v):
            val = v / 10.0
            self.speed_label.setText(f"{val}")
            self.parent_window.set_speed(val)
            
        self.speed_slider.valueChanged.connect(on_speed_change)
        speed_layout.addWidget(self.speed_slider)
        speed_layout.addWidget(self.speed_label)
        form_layout.addRow("🚀 滚动速度:", speed_layout)
        
        self.outline_spin = QDoubleSpinBox()
        self.outline_spin.setRange(0.0, 10.0)
        self.outline_spin.setSingleStep(0.1)
        self.outline_spin.setDecimals(1)
        self.outline_spin.setValue(self.parent_window.outline_width)
        self.outline_spin.valueChanged.connect(self.parent_window.set_outline_width)
        form_layout.addRow("✒️ 描边粗细:", self.outline_spin)

        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(50, 255)
        self.opacity_slider.setValue(self.parent_window.danmaku_opacity)
        self.opacity_slider.valueChanged.connect(self.parent_window.set_opacity)
        form_layout.addRow("👻 弹幕不透明度:", self.opacity_slider)
        
        main_layout.addLayout(form_layout)
        
        btn_layout = QHBoxLayout()
        self.apply_room_btn = QPushButton("🔄 应用并重启监听")
        self.apply_room_btn.clicked.connect(self.apply_room_changes)
        btn_layout.addWidget(self.apply_room_btn)
        
        main_layout.addLayout(btn_layout)
        self.setLayout(main_layout)

    def apply_room_changes(self):
        text = self.room_edit.text()
        try:
            new_ids = [int(x.strip()) for x in text.replace('，', ',').split(',') if x.strip().isdigit()]
            if not new_ids:
                QMessageBox.warning(self, "提示", "请输入有效的直播间 ID")
                return
            self.parent_window.update_rooms(new_ids)
            QMessageBox.information(self, "成功", f"已更新监听列表: {new_ids}")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"格式错误: {e}")

# ================= 主弹幕窗口 =================
class DanmakuWindow(QWidget):
    new_danmaku_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        self.config = load_config()

        self.room_ids = self.config.get("room_ids", [])
        self.font_size = self.config.get("font_size", 28)
        self.line_limit = self.config.get("line_limit", 0)
        self.speed_base = self.config.get("speed_base", 2.5)
        self.outline_width = self.config.get("outline_width", 1.5)
        self.danmaku_opacity = self.config.get("opacity", 255)

        self.danmakus = []
        self.is_locked = False
        self.drag_position = None
        self.font = QFont('Microsoft YaHei', self.font_size, QFont.Bold)
        self.lane_status = {}
        self.lock_button_rect = None

        # --- 新增：等待队列 ---
        # 当屏幕满时，弹幕暂存到这里，而不是强行重叠
        # maxlen=100 表示最多缓存100条，再多就丢弃旧的，防止内存爆炸
        self.danmaku_queue = deque(maxlen=100)
        
        self.monitor = LiveMonitor(self.new_danmaku_signal)
        
        self.initUI()
        self.initTrayIcon()
        
        self.new_danmaku_signal.connect(self.add_danmaku)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_danmakus)
        self.timer.start(16)
        
        self.monitor.start(self.room_ids)

    def initUI(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        screen_rect = QApplication.primaryScreen().geometry()
        self.setGeometry(screen_rect.width() // 4, screen_rect.height() // 4, 1920, 500)
        
        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(20, 20)
        self.size_grip.raise_()
        self.show()

    def initTrayIcon(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(QStyle.SP_DesktopIcon))
        self.tray_menu = QMenu()
        
        self.settings_action = QAction("⚙️ 弹幕配置", self)
        self.settings_action.triggered.connect(self.open_settings)
        self.tray_menu.addAction(self.settings_action)
        self.tray_menu.addSeparator()
        
        self.lock_action = QAction("🔒 锁定并穿透", self)
        self.lock_action.triggered.connect(lambda: self.set_locked_mode(True))
        self.tray_menu.addAction(self.lock_action)
        
        self.unlock_action = QAction("🔓 解锁编辑", self)
        self.unlock_action.triggered.connect(lambda: self.set_locked_mode(False))
        self.tray_menu.addAction(self.unlock_action)
        
        self.tray_menu.addSeparator()
        self.quit_action = QAction("❌ 退出程序", self)
        self.quit_action.triggered.connect(self.close_app)
        self.tray_menu.addAction(self.quit_action)
        
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()
        self.update_tray_menu()

    def save_current_config(self):
        cfg = {
            "room_ids": self.room_ids,
            "font_size": self.font_size,
            "line_limit": self.line_limit,
            "speed_base": self.speed_base,
            "outline_width": self.outline_width,
            "opacity": self.danmaku_opacity
        }
        save_config(cfg)

    def update_rooms(self, new_ids):
        self.room_ids = new_ids
        self.save_current_config()
        self.monitor.start(self.room_ids)

    # --- 属性设置 ---
    def set_font_size(self, size):
        self.font_size = size
        self.font.setPointSize(size)
        self.lane_status.clear()
        self.danmakus.clear()
        self.danmaku_queue.clear() # 字体变了，清空队列防止错位
        self.save_current_config()

    def set_line_limit(self, lines):
        self.line_limit = lines
        self.save_current_config()

    def set_speed(self, speed):
        self.speed_base = speed
        self.save_current_config()

    def set_outline_width(self, size):
        self.outline_width = float(size)
        self.danmakus.clear() 
        self.update()
        self.save_current_config()

    def set_opacity(self, opacity):
        self.danmaku_opacity = opacity
        self.update()
        self.save_current_config()

    def open_settings(self):
        if not hasattr(self, 'settings_dialog') or not self.settings_dialog.isVisible():
            self.settings_dialog = SettingsDialog(self)
            self.settings_dialog.show()
        else:
            self.settings_dialog.activateWindow()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.set_locked_mode(not self.is_locked)

    def update_tray_menu(self):
        self.lock_action.setVisible(not self.is_locked)
        self.unlock_action.setVisible(self.is_locked)

    def set_locked_mode(self, locked):
        self.is_locked = locked
        self.update_tray_menu()
        rect = self.geometry()
        self.hide()
        
        if self.is_locked:
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput | Qt.Tool)
            self.size_grip.hide()
        else:
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
            self.size_grip.show()
            
        self.setGeometry(rect)
        self.show()
    
    def close_app(self):
        self.monitor.stop()
        self.save_current_config()
        QApplication.instance().quit()

    def mousePressEvent(self, event):
        if not self.is_locked and event.button() == Qt.LeftButton:
            if self.lock_button_rect and self.lock_button_rect.contains(event.pos()):
                self.set_locked_mode(True)
                return
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if not self.is_locked and event.buttons() == Qt.LeftButton and self.drag_position:
            self.move(event.globalPos() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        if not self.is_locked and self.drag_position:
            snap_threshold = 20
            pos = self.pos()

            for screen in QApplication.screens():
                screen_geo = screen.geometry()
                window_rect = self.geometry()

                if screen_geo.intersects(window_rect):
                    rel_x = pos.x() - screen_geo.x()
                    rel_y = pos.y() - screen_geo.y()

                    if rel_x < snap_threshold:
                        pos.setX(screen_geo.x())
                    elif rel_x + self.width() > screen_geo.width() - snap_threshold:
                        pos.setX(screen_geo.x() + screen_geo.width() - self.width())

                    if rel_y < snap_threshold:
                        pos.setY(screen_geo.y())
                    elif rel_y + self.height() > screen_geo.height() - snap_threshold:
                        pos.setY(screen_geo.y() + screen_geo.height() - self.height())

                    self.move(pos)
                    break

        self.drag_position = None

    def resizeEvent(self, event):
        self.size_grip.move(self.width() - self.size_grip.width(), self.height() - self.size_grip.height())
        super().resizeEvent(event)

    # --- 核心：缓存图片生成 ---
    def generate_danmaku_pixmap(self, text):
        fm = QFontMetrics(self.font)
        text_w = fm.width(text)
        text_h = fm.height()
        
        margin = int(self.outline_width * 2) + 2
        w = text_w + margin * 2
        h = text_h + margin * 2
        
        pixmap = QPixmap(w, h)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(self.font)
        
        x = margin
        y = margin + fm.ascent()
        
        path = QPainterPath()
        path.addText(x, y, self.font, text)
        
        if self.outline_width > 0:
            painter.setPen(QPen(QColor(0, 0, 0), self.outline_width, Qt.SolidLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawPath(path)
        
        painter.end()
        return pixmap, w 

    # --- 核心：尝试发射弹幕 (如果成功返回True，失败返回False) ---
    def try_spawn_danmaku(self, text):
        fm = QFontMetrics(self.font)
        track_height = fm.height() + 2
        
        # 注意：这里我们还没生成图片，先不消耗资源
        # 估算宽度用于碰撞检测
        # (稍微加一点冗余，因为实际生成时有描边margin)
        text_width_approx = fm.width(text) + (self.outline_width * 2) + 10
        
        physical_max = max(1, self.height() // track_height)
        if self.line_limit > 0:
            max_tracks = min(self.line_limit, physical_max)
        else:
            max_tracks = physical_max
        
        track_indices = list(range(max_tracks))
        random.shuffle(track_indices)
        
        selected_track = -1
        current_fixed_speed = self.speed_base 
        final_speed = current_fixed_speed
        
        safe_margin = 20
        
        # 寻找可用轨道
        for i in track_indices:
            if i not in self.lane_status:
                selected_track = i
                final_speed = current_fixed_speed
                break
            
            last_item = self.lane_status[i]
            
            # 严格防重叠：如果上一条还没走远，绝对不在此轨道发射
            if last_item['end_x'] > (self.width() - safe_margin):
                continue 
            
            # 速度防追尾
            prev_speed = last_item['speed']
            if current_fixed_speed > prev_speed:
                final_speed = prev_speed 
            else:
                final_speed = current_fixed_speed
            
            selected_track = i
            break
        
        # 如果所有轨道都满了 (selected_track 还是 -1)
        if selected_track == -1:
            return False # 发射失败，需要排队

        # --- 发射成功，正式生成资源 ---
        pixmap, real_width = self.generate_danmaku_pixmap(text)
        
        y = selected_track * track_height
        margin = int(self.outline_width * 2) + 2
        offset_y = (track_height - pixmap.height()) // 2
        
        danmaku_obj = {
            'pixmap': pixmap,
            'x': float(self.width()),
            'y': float(y + offset_y),
            'width': real_width,
            'track': selected_track,
            'current_speed': final_speed
        }
        
        self.danmakus.append(danmaku_obj)
        self.lane_status[selected_track] = {
            'end_x': float(self.width()) + real_width - (margin * 2), 
            'speed': final_speed
        }
        return True

    # --- 信号入口：新弹幕来了 ---
    def add_danmaku(self, text):
        # 1. 尝试直接发射
        if not self.try_spawn_danmaku(text):
            # 2. 如果屏幕满了，加入队列
            self.danmaku_queue.append(text)

    # --- 定时器循环 ---
    def update_danmakus(self):
        # 1. 优先处理排队中的弹幕
        # 每次循环尝试把队列里的发出去，直到发不出去或者队列空了
        # 限制每次最多发多少个？其实不用限制，能发就发，填满为止
        while self.danmaku_queue:
            next_text = self.danmaku_queue[0] # 看一眼队头
            if self.try_spawn_danmaku(next_text):
                self.danmaku_queue.popleft() # 发射成功，移出队列
            else:
                break # 依然满屏，下一帧再说

        # 2. 更新现有弹幕位置
        active_danmakus = []
        for d in self.danmakus:
            d['x'] -= self.speed_base
            if d['x'] + d['width'] > -50:
                active_danmakus.append(d)
        
        self.danmakus = active_danmakus
        
        # 3. 更新轨道状态
        to_remove = []
        for track_id, status in self.lane_status.items():
            status['end_x'] -= self.speed_base 
            if status['end_x'] < 0:
                to_remove.append(track_id)
        for k in to_remove:
            del self.lane_status[k]

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)

        if not self.is_locked:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 150))

            button_width = 140
            button_height = 40
            button_x = (self.width() - button_width) // 2
            button_y = self.height() // 2 + 60
            from PyQt5.QtCore import QRect
            self.lock_button_rect = QRect(button_x, button_y, button_width, button_height)

            painter.setBrush(QColor(70, 130, 180))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(self.lock_button_rect, 10, 10)

            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont('Microsoft YaHei', 12, QFont.Bold))
            painter.drawText(self.lock_button_rect, Qt.AlignCenter, "进入穿透模式")

            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont('Microsoft YaHei', 14, QFont.Bold))
            tips = "【编辑模式】\n\n1. 拖动窗口移动\n2. 拖动右下角调整大小\n3. 双击托盘图标开关穿透模式"
            text_rect = self.rect().adjusted(0, 0, 0, -80)
            painter.drawText(text_rect, Qt.AlignCenter, tips)

        if self.danmaku_opacity < 255:
            painter.setOpacity(self.danmaku_opacity / 255.0)

        for d in self.danmakus:
            painter.drawPixmap(int(d['x']), int(d['y']), d['pixmap'])

        painter.setOpacity(1.0)

if __name__ == '__main__':
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    win = DanmakuWindow()
    
    sys.exit(app.exec_())