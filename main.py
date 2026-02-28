import os
import sys

# CRITICAL FIX for Windows OSError 1114:
# Torch and its dependencies MUST be imported before PyQt6 on some Windows systems 
# to avoid DDL initialization routine failures.
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
try:
    import torch
    import stable_whisper
except ImportError:
    pass

import logging
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSettings

from ui.overlay_window import LyricsOverlay
from ui.tray_manager import TrayManager
from core.audio_poller import AudioPoller

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False) 
    
    settings = QSettings("WordPlay", "Overlay")

    # 1. Initialize Modules
    overlay = LyricsOverlay(settings)
    tray_manager = TrayManager(settings=settings)
    audio_poller = AudioPoller(poll_interval_ms=3000)

    # 2. Connect Signals (Decoupled architecture)
    
    # Audio Poller -> Overlay
    audio_poller.device_changed.connect(overlay.update_audio_device)
    
    # Tray Manager -> Overlay UI Commands
    tray_manager.toggle_visibility.connect(overlay.toggle_visibility)
    tray_manager.toggle_click_through.connect(overlay.set_click_through_mode)
    tray_manager.theme_changed.connect(overlay.set_theme)
    tray_manager.opacity_changed.connect(overlay.set_opacity)
    tray_manager.force_re_sync.connect(overlay.force_re_sync)

    # Overlay UI -> Tray Manager State
    overlay.tray_icon_update.connect(tray_manager.set_icon_state)
    overlay.tray_tooltip_update.connect(tray_manager.update_tooltip)
    overlay.tray_track_update.connect(tray_manager.update_track_info)

    # 3. Boot Application
    overlay.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
