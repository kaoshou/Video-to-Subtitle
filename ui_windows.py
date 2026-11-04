"""Build dialogs offscreen and map them once, at their final geometry."""
import sys
import tkinter as tk
import customtkinter as ctk


class DialogWindow(ctk.CTkToplevel):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.withdraw()

    def _windows_set_titlebar_color(self, color_mode):
        # CTk's default implementation calls update() and schedules a remap
        # inside __init__, before the caller can withdraw or position us.
        # DWM can update the existing native titlebar without either operation.
        if not sys.platform.startswith('win'):
            return
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            value = ctypes.c_int(str(color_mode).lower() == 'dark')
            for attribute in (20, 19):
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                    break
        except (OSError, AttributeError):
            pass


def show_dialog(window, parent, width, height, *, modal=False):
    """Finish layout while withdrawn; never process arbitrary events mid-build."""
    window.withdraw()
    if parent is not None and parent.winfo_exists() and sys.platform != 'darwin':
        window.transient(parent)
    window.geometry(f'{width}x{height}')
    window.update_idletasks()
    scale = window._get_window_scaling()
    actual_width = round(max(width, window._min_width) * scale)
    actual_height = round(max(height, window._min_height) * scale)
    if parent is not None and parent.winfo_exists() and parent.state() != 'withdrawn':
        x = parent.winfo_rootx() + (parent.winfo_width() - actual_width) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - actual_height) // 2
    else:
        x = (window.winfo_screenwidth() - actual_width) // 2
        y = (window.winfo_screenheight() - actual_height) // 2
    x = max(0, min(x, max(0, window.winfo_screenwidth() - actual_width)))
    y = max(0, min(y, max(0, window.winfo_screenheight() - actual_height - 40)))
    # Coordinates are physical screen pixels, unlike CTk's logical dimensions.
    tk.Wm.geometry(window, f'{actual_width}x{actual_height}+{x}+{y}')
    window.update_idletasks()
    window.attributes('-alpha', 1.0)
    window.deiconify()
    window.lift()
    # Preserve the original user-opened dialog activation semantics. On
    # Windows, focus_set alone may leave keyboard input in the parent window.
    window.focus_force()
    if modal and sys.platform != 'darwin':
        window.grab_set()
