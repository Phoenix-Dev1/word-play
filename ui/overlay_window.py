import logging
import random
from dataclasses import dataclass

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QGraphicsDropShadowEffect
from PyQt6.QtCore import Qt, QTimer, QPoint, QPropertyAnimation, QEasingCurve, QSettings, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPixmap, QCursor, QFontMetrics

from core.window_utils import WindowUtils
from ui.components import SmoothScrollArea
from ui.styles import StyleProvider
from ui.constants import SYNC_PHRASES
from media_listener import MediaListener
from lyrics_manager import LyricsManager

logger = logging.getLogger(__name__)

@dataclass
class AppState:
    current_song_key: str = ""
    is_fetching: bool = False
    current_audio_device: str = "Unknown"
    is_transparent: bool = False
    force_click_through: bool = False
    is_light_theme: bool = False

class LyricsOverlay(QWidget):
    """
    The main transparent UI window overlay for displaying synced lyrics.
    It manages its own layout, animations, and coordinates with MediaListener and LyricsManager.
    """
    # Signals to Tray Manager
    tray_icon_update = pyqtSignal(str)
    tray_tooltip_update = pyqtSignal(str)
    tray_track_update = pyqtSignal(str)

    def __init__(self, settings: QSettings):
        super().__init__()
        self.settings = settings
        self.state = AppState()
        self.state.is_light_theme = self.settings.value("theme", "dark") == "light"
        
        self.is_dragging = False
        self.drag_start_pos = QPoint()
        self._is_interactable = False
        self.pending_image_data = None
        self.last_unsynced_text = ""

        # Window Setup
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.hwnd = int(self.winId())
        WindowUtils.set_click_through(self.hwnd, True)

        self._init_ui()

        # Engine Setup
        self.listener = MediaListener()
        self.listener.start_listening_in_background()
        
        self.lyrics_manager = LyricsManager()
        self.lyrics_manager._main_ui_ref = self 
        
        self.lyrics_manager.lyrics_found.connect(self.on_lyrics_found)
        self.lyrics_manager.alignment_started.connect(self.on_alignment_started)
        self.lyrics_manager.alignment_finished.connect(self.on_alignment_finished)

        # Syncing Phrases State
        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self.update_sync_message)
        self.sync_msg_index = 0
        self.shuffled_phrases = []

        # Main Update Timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_ui)
        self.timer.start(100)

        # Geometry Setup
        self.setFixedWidth(500)
        self.setMinimumHeight(466)
        self.adjustSize()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        self.container = QFrame()
        self.container.setObjectName("container")
        self.container.setStyleSheet(StyleProvider.get_container_style(self.state.is_light_theme, False))
        
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(20, 20, 20, 10)
        container_layout.setSpacing(15)

        # Header
        header_layout = QHBoxLayout()
        self.art_label = QLabel()
        self.art_label.setFixedSize(64, 64)
        self.art_label.setStyleSheet("background-color: rgba(255,255,255,20); border-radius: 8px;")
        
        info_layout = QVBoxLayout()
        self.title_label = QLabel("Waiting for music...")
        self.title_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.artist_label = QLabel("")
        self.artist_label.setFont(QFont("Segoe UI", 10))
        
        info_layout.addWidget(self.title_label)
        info_layout.addWidget(self.artist_label)
        info_layout.addStretch()

        controls_layout = QVBoxLayout()
        controls_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        
        self.drag_hint = QLabel("Drag (Hold Ctrl)")
        self.drag_hint.setStyleSheet("color: #888888; font-size: 10px;")
        
        self.close_btn = QLabel("Click to hide")
        self.close_btn.setStyleSheet("color: #aaaaaa; font-size: 10px;")
        self.close_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.close_btn.mousePressEvent = self.on_close_clicked
        
        controls_layout.addWidget(self.drag_hint)
        controls_layout.addWidget(self.close_btn)

        header_layout.addWidget(self.art_label)
        header_layout.addLayout(info_layout, stretch=1)
        header_layout.addLayout(controls_layout)
        container_layout.addLayout(header_layout)

        # Lyrics Section
        self.lyric_labels = []
        for i in range(5):
            lbl = QLabel()
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            lbl.setWordWrap(True)
            if i == 2:
                lbl.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
                shadow = QGraphicsDropShadowEffect()
                shadow.setBlurRadius(10)
                shadow.setColor(QColor(0, 0, 0, 200))
                shadow.setOffset(0, 0)
                lbl.setGraphicsEffect(shadow)
            else:
                lbl.setFont(QFont("Segoe UI", 13))
            
            container_layout.addWidget(lbl)
            self.lyric_labels.append(lbl)

        # Unsynced Section
        self.scroll_area = SmoothScrollArea(self.container)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.verticalScrollBar().setStyleSheet(StyleProvider.get_scrollbar_style())
        self.scroll_area.hide()
        
        self.unsynced_label = QLabel()
        self.unsynced_label.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignTop)
        self.unsynced_label.setWordWrap(True)
        self.scroll_area.setWidget(self.unsynced_label)
        container_layout.addWidget(self.scroll_area)

        # Footer
        self.output_label = QLabel("Output: Loading...")
        self.output_label.setStyleSheet("color: #666666; font-size: 10px;")
        self.output_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(self.output_label)

        main_layout.addWidget(self.container)
        
        # Apply initial font theme colors
        StyleProvider.apply_theme_to_labels(
            self.state.is_light_theme, 
            self.title_label, 
            self.artist_label, 
            self.lyric_labels, 
            self.unsynced_label
        )

    # Mouse Events
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.state.is_transparent:
            self.is_dragging = True
            self.drag_start_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.is_dragging:
            self.move(event.globalPosition().toPoint() - self.drag_start_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = False
            event.accept()

    def on_close_clicked(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.state.is_transparent:
            self.hide_with_animation()

    # Animations
    def hide_with_animation(self):
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(300)
        self.anim.setStartValue(self.windowOpacity())
        self.anim.setEndValue(0.0)
        self.anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.anim.finished.connect(self.hide)
        self.anim.start()

    def show_with_animation(self):
        self.show()
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(300)
        self.anim.setStartValue(0.0)
        target_opacity = float(self.settings.value("opacity", 1.0))
        self.anim.setEndValue(target_opacity)
        self.anim.setEasingCurve(QEasingCurve.Type.InQuad)
        self.anim.start()

    def toggle_visibility(self):
        if self.isVisible() and self.windowOpacity() > 0:
            self.hide_with_animation()
        else:
            self.show_with_animation()

    def update_sync_message(self):
        if not self.lyrics_manager.is_aligning:
            return
            
        if not self.shuffled_phrases or self.sync_msg_index >= len(self.shuffled_phrases):
            self.shuffled_phrases = SYNC_PHRASES[:]
            random.shuffle(self.shuffled_phrases)
            self.sync_msg_index = 0
            
        new_msg = f"⚙️ {self.shuffled_phrases[self.sync_msg_index]}"
        self.sync_msg_index += 1
        
        # Premium Fade Transition
        self.fade_out_anim = QPropertyAnimation(self.lyric_labels[2], b"windowOpacity") # Note: windowOpacity doesn't work for widgets directly
        # Instead, use a simple text update for now or a custom opacity effect if needed.
        # Given the constraint of simplicity, let's just update the text with a quick prefix.
        self.lyric_labels[2].setText(new_msg)

    # Slot Commands from Tray Manager
    def update_audio_device(self, new_device: str):
        self.state.current_audio_device = new_device

    def force_re_sync(self):
        if not self.listener.is_playing or not self.state.current_song_key:
            return
        logger.info("UI: Manual force sync requested.")
        title = self.listener.current_title
        artist = self.listener.current_artist
        
        self.lyrics_manager.is_synced = False
        self.lyrics_manager.synced_lyrics = []
        if self.lyrics_manager.sync_manager:
            self.lyrics_manager.sync_manager.force_queue_sync(title, artist)
        self.lyrics_manager.fetch_lyrics(title, artist)

    def set_click_through_mode(self, enabled: bool):
        self.state.force_click_through = enabled

    def set_theme(self, is_light: bool):
        self.state.is_light_theme = is_light
        # The update_ui loop handles container changes, but we apply fonts immediately here
        StyleProvider.apply_theme_to_labels(
            is_light, self.title_label, self.artist_label, self.lyric_labels, self.unsynced_label
        )
        self._is_interactable = None # Force a style refresh on next tick
        
    def set_opacity(self, opacity: float):
        if self.isVisible():
            self.setWindowOpacity(opacity)

    # Engine Callbacks
    def on_lyrics_found(self, success):
        self.state.is_fetching = False
        if not success:
            for i in range(5):
                self.lyric_labels[i].setText("No Lyrics Found" if i == 2 else "")

    def on_alignment_started(self):
        logger.info("UI: AI Alignment Started...")
        self.lyric_labels[2].setText("⚙️ AI Syncing Audio...")
        self.shuffled_phrases = [] # Reset shuffle for each song
        self.sync_msg_index = 0
        self.sync_timer.start(3000) # 3 seconds interval

    def on_alignment_finished(self, success, song_key):
        self.sync_timer.stop()
        if song_key != self.state.current_song_key:
            logger.info(f"UI: Ignoring alignment result for old song: {song_key}")
            return
        if success:
            logger.info("UI: AI Alignment Finished Successfully!")
        else:
            logger.info("UI: AI Alignment Failed.")

    def truncate_text(self, label, text):
        metrics = QFontMetrics(label.font())
        elided_text = metrics.elidedText(text, Qt.TextElideMode.ElideRight, 250)
        label.setText(elided_text)

    # Core UI Update Loop
    def update_ui(self):
        # 1. Update output label
        display_device = self.state.current_audio_device
        if display_device == "Unknown" and self.listener.source_app_id:
            raw_id = self.listener.source_app_id.lower()
            if "spotify" in raw_id:
                display_device = "Spotify"
            else:
                display_device = raw_id.split(".")[0].capitalize()
        
        self.output_label.setText(f"Output: {display_device}")

        # 2. Handle Ctrl-Drag interaction & Hover State
        ctrl_pressed = WindowUtils.is_ctrl_pressed()
        mouse_over_window = self.geometry().contains(QCursor.pos())
        
        if self.state.force_click_through:
            should_be_interactable = False
        else:
            should_be_interactable = ctrl_pressed and mouse_over_window

        if should_be_interactable != self._is_interactable:
            self._is_interactable = should_be_interactable
            
            if should_be_interactable:
                WindowUtils.set_click_through(self.hwnd, False)
                self.container.setStyleSheet(StyleProvider.get_container_style(self.state.is_light_theme, True))
                self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                WindowUtils.set_click_through(self.hwnd, True)
                self.container.setStyleSheet(StyleProvider.get_container_style(self.state.is_light_theme, False))
                self.close_btn.setCursor(Qt.CursorShape.ArrowCursor)
            
            # Refresh visibility
            self.show()

        self.state.is_transparent = not self._is_interactable

        # 3. Check Image Download
        if self.pending_image_data:
            pixmap = QPixmap()
            pixmap.loadFromData(self.pending_image_data)
            pixmap = pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.art_label.setPixmap(pixmap)
            self.pending_image_data = None

        # 4. Check Media State (Handled by Main App via signals ideally, but integrated here for now)
        if not self.listener.is_playing:
            self.tray_icon_update.emit("paused")
            self.tray_tooltip_update.emit("Word-Play: Paused")
            self.tray_track_update.emit("Music Paused")
            self.lyric_labels[2].setText("Music Paused or Stopped")
            for i in [0, 1, 3, 4]: self.lyric_labels[i].setText("")
            return

        title = self.listener.current_title
        artist = self.listener.current_artist
        if not title or not artist:
            return

        song_key = f"{artist} - {title}"
        
        # 5. Handle Song Change
        if song_key != self.state.current_song_key:
            logger.info(f"UI: Song changed to: {song_key}")
            self.state.current_song_key = song_key
            self.lyrics_manager.current_song_key = song_key
            
            if hasattr(self.lyrics_manager, 'alignment_worker') and self.lyrics_manager.alignment_worker:
                self.lyrics_manager.alignment_worker.cancel()
                
            self.truncate_text(self.title_label, title)
            self.truncate_text(self.artist_label, artist)
            self.art_label.clear()
            self.art_label.setText("") 
            
            for i in range(5):
                self.lyric_labels[i].setText("Loading..." if i == 2 else "")
                
            self.state.is_fetching = True
            for i in range(5):
                self.lyric_labels[i].setText("Searching..." if i == 2 else "")
            
            self.lyrics_manager.fetch_lyrics(title, artist)
            return
            
        if self.state.is_fetching:
            self.lyric_labels[2].setText("Searching..." if "Searching" not in self.lyric_labels[2].text() else self.lyric_labels[2].text())
            return

        # 6. Update Lyrics Context
        if getattr(self.lyrics_manager, 'is_aligning', False):
            self.tray_icon_update.emit("syncing")
            self.tray_tooltip_update.emit(f"Word-Play: Syncing - {song_key}")
            self.tray_track_update.emit(song_key)
            self.scroll_area.hide()
            for lbl in self.lyric_labels:
                lbl.show()
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                
            self.lyric_labels[0].setText("")
            self.lyric_labels[1].setText("")
            # self.lyric_labels[2].setText("⚙️ AI Syncing Audio...")  # Removed: Conflicting with dynamic sync_timer
            self.lyric_labels[2].setStyleSheet("color: #aaddff;" if not self.state.is_light_theme else "color: #0055ff;")
            self.lyric_labels[3].setText("This might take a minute")
            self.lyric_labels[4].setText("")
            
        elif getattr(self.lyrics_manager, 'plain_lyrics', None) and not getattr(self.lyrics_manager, 'is_synced', False):
            self.tray_icon_update.emit("default")
            self.tray_tooltip_update.emit(f"Word-Play: Plain Text - {song_key}")
            self.tray_track_update.emit(song_key)
            for lbl in self.lyric_labels:
                lbl.hide()
            
            # Re-apply theme color
            color = "black" if self.state.is_light_theme else "white"
            self.lyric_labels[2].setStyleSheet(f"color: {color};")
                
            self.scroll_area.show()
            current_text = self.lyrics_manager.plain_lyrics
            
            if current_text != self.last_unsynced_text:
                self.last_unsynced_text = current_text
                self.unsynced_label.setText(current_text)
                    
        elif getattr(self.lyrics_manager, 'synced_lyrics', None):
            self.tray_icon_update.emit("default")
            self.tray_tooltip_update.emit(f"Word-Play: Synced - {song_key}")
            self.tray_track_update.emit(song_key)
            self.scroll_area.hide()
            
            color = "black" if self.state.is_light_theme else "white"
            self.lyric_labels[2].setStyleSheet(f"color: {color};")
            
            for lbl in self.lyric_labels:
                lbl.show()
                
            pos = self.listener.current_position
            past, current, future, is_rtl = self.lyrics_manager.get_lyrics_context(pos, past_lines_count=2, future_lines_count=2)
            
            if is_rtl:
                self.container.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
                alignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter
            else:
                self.container.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
                alignment = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
                
            for lbl in self.lyric_labels:
                lbl.setAlignment(alignment)
            
            if len(past) == 2:
                self.lyric_labels[0].setText(past[0])
                self.lyric_labels[1].setText(past[1])
            elif len(past) == 1:
                self.lyric_labels[0].setText("")
                self.lyric_labels[1].setText(past[0])
            else:
                self.lyric_labels[0].setText("")
                self.lyric_labels[1].setText("")
                
            self.lyric_labels[2].setText(current if current else "♫")
            
            self.lyric_labels[3].setText(future[0] if len(future) > 0 else "")
            self.lyric_labels[4].setText(future[1] if len(future) > 1 else "")
                
        else:
            self.scroll_area.hide()
            color = "black" if self.state.is_light_theme else "white"
            self.lyric_labels[2].setStyleSheet(f"color: {color};")
            self.lyric_labels[2].setText("♫ Lyrics not found for this version" if self.listener.current_position > 5 else "♫ Searching...")
            for i in [0, 1, 3, 4]: self.lyric_labels[i].setText("")
            
        self.adjustSize()
