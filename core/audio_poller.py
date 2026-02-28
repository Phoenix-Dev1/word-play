import threading
from PyQt6.QtCore import QObject, pyqtSignal, QTimer

class AudioPoller(QObject):
    """
    Background worker that polls the system audio hardware using pycaw.
    Emits device_changed when the active output device name updates.
    """
    device_changed = pyqtSignal(str)

    def __init__(self, parent=None, poll_interval_ms=3000):
        super().__init__(parent)
        self.current_audio_device = "Unknown"
        
        self.hw_timer = QTimer(self)
        self.hw_timer.timeout.connect(self.poll_audio_device)
        self.hw_timer.start(poll_interval_ms)
        self.poll_audio_device() # Initial poll

    def poll_audio_device(self):
        """Fires a background thread to safely query COM objects."""
        def worker():
            try:
                import pythoncom
                from pycaw.pycaw import AudioUtilities
                pythoncom.CoInitialize()
                device = AudioUtilities.GetSpeakers()
                if device:
                    new_device = device.FriendlyName
                    if new_device != self.current_audio_device:
                        self.current_audio_device = new_device
                        self.device_changed.emit(new_device)
                pythoncom.CoUninitialize()
            except Exception:
                pass
                
        threading.Thread(target=worker, daemon=True).start()
