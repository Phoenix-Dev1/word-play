import os
import sys
import winreg
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PyQt6.QtCore import QObject, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QDesktopServices, QPixmap, QPainter, QColor, QIcon

class TrayManager(QObject):
    """
    Manages the System Tray icon, context menu actions, and user configuration.
    Communicates with the main application layer exclusively via Signals.
    """
    
    # Emitted when configuration toggles are clicked
    toggle_click_through = pyqtSignal(bool)
    theme_changed = pyqtSignal(bool) # True if light theme
    opacity_changed = pyqtSignal(float)
    force_re_sync = pyqtSignal()
    toggle_visibility = pyqtSignal()
    
    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        self.settings = settings
        
        self.tray_icon = QSystemTrayIcon(self)
        self.set_icon_state("default")
        
        self.tray_menu = QMenu()
        self._build_menu()
        
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.setToolTip("Word-Play: Waiting for music...")
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def _build_menu(self):
        # Current Track Tracker
        self.track_info_action = QAction("No track playing...", self)
        self.track_info_action.setEnabled(False)
        self.tray_menu.addAction(self.track_info_action)
        self.tray_menu.addSeparator()

        # Context Control
        self.click_through_action = QAction("Click-Through Mode", self)
        self.click_through_action.setCheckable(True)
        self.click_through_action.toggled.connect(self.toggle_click_through.emit)
        self.tray_menu.addAction(self.click_through_action)

        self.visibility_action = QAction("Show/Hide Lyrics", self)
        self.visibility_action.triggered.connect(self.toggle_visibility.emit)
        self.tray_menu.addAction(self.visibility_action)

        force_sync_action = QAction("Force Re-sync Current Song", self)
        force_sync_action.triggered.connect(self.force_re_sync.emit)
        self.tray_menu.addAction(force_sync_action)
        self.tray_menu.addSeparator()

        # Settings
        settings_menu = self.tray_menu.addMenu("Settings")
        
        self.startup_action = QAction("Run on Windows Startup", self)
        self.startup_action.setCheckable(True)
        self.startup_action.setChecked(self._check_run_on_startup())
        self.startup_action.toggled.connect(self._toggle_run_on_startup)
        settings_menu.addAction(self.startup_action)
        settings_menu.addSeparator()

        self.theme_action = QAction("Light Theme", self)
        self.theme_action.setCheckable(True)
        is_light = self.settings.value("theme", "dark") == "light"
        self.theme_action.setChecked(is_light)
        self.theme_action.toggled.connect(self._on_theme_toggled)
        settings_menu.addAction(self.theme_action)

        opacity_menu = settings_menu.addMenu("Opacity")
        self.opacity_group = []
        current_opacity = float(self.settings.value("opacity", 1.0))
        
        for level in [25, 50, 75, 100]:
            action = QAction(f"{level}%", self)
            action.setCheckable(True)
            if abs(current_opacity - (level/100.0)) < 0.01:
                action.setChecked(True)
            action.triggered.connect(lambda checked, l=level: self._on_opacity_preset(l))
            opacity_menu.addAction(action)
            self.opacity_group.append(action)

        self.tray_menu.addSeparator()

        exit_action = QAction("Exit Word-Play", self)
        exit_action.triggered.connect(QApplication.instance().quit)
        self.tray_menu.addAction(exit_action)

    def set_icon_state(self, state="default"):
        """Redraws the physical icon based on string flags."""
        from ui.icon_provider import TrayIconProvider
        self.tray_icon.setIcon(TrayIconProvider.get_icon(state))

    def update_tooltip(self, text: str):
        self.tray_icon.setToolTip(text)
        
    def update_track_info(self, text: str):
        self.track_info_action.setText(text)

    def on_tray_activated(self, reason):
        if reason in [QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick]:
            self.toggle_visibility.emit()

    def _on_theme_toggled(self, is_light: bool):
        self.settings.setValue("theme", "light" if is_light else "dark")
        self.theme_changed.emit(is_light)

    def _on_opacity_preset(self, level: int):
        for action in self.opacity_group:
            action.setChecked(False)
        sender_action = self.sender()
        if sender_action:
            sender_action.setChecked(True)
            
        opacity = level / 100.0
        self.settings.setValue("opacity", opacity)
        self.opacity_changed.emit(opacity)

    def _check_run_on_startup(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
            value, _ = winreg.QueryValueEx(key, "WordPlay")
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            return False
            
    def _toggle_run_on_startup(self, checked):
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        if checked:
            app_path = os.path.abspath(sys.argv[0])
            if app_path.endswith('.py'):
                cmd = f'"{sys.executable}" "{app_path}"'
            else:
                cmd = f'"{app_path}"'
            winreg.SetValueEx(key, "WordPlay", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, "WordPlay")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
