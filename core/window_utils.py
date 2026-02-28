import ctypes

class WindowUtils:
    """Helper class to abstract away Win32 API calls."""
    
    @staticmethod
    def set_click_through(hwnd: int, enabled: bool):
        """Toggles the WS_EX_TRANSPARENT extended window style."""
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_LAYERED = 0x00080000
        GWL_EXSTYLE = -20
        user32 = ctypes.windll.user32
        
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        
        if enabled:
            # Add transparent flag
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        else:
            # Remove transparent flag
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (style | WS_EX_LAYERED) & ~WS_EX_TRANSPARENT)

    @staticmethod
    def is_ctrl_pressed() -> bool:
        """Checks if the Control key is currently held down natively."""
        user32 = ctypes.windll.user32
        return (user32.GetAsyncKeyState(0x11) & 0x8000) != 0
