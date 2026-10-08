"""Shared native CTk palette and Chinese-capable typography."""
import platform

BACKGROUND = ('#F4F7FB', '#171D28')
CARD = ('#FFFFFF', '#222D3D')
SURFACE = ('#EDF2F8', '#304159')
BORDER = ('#DCE4EF', '#344257')
TEXT = ('#243C59', '#DFE9F7')
MUTED = ('#65748A', '#A5B2C5')
ACCENT = ('#2468B4', '#367FCB')
HOVER = ('#1C5697', '#438DD9')
FONT_FAMILY = {'Windows': 'Microsoft JhengHei UI', 'Darwin': 'PingFang TC'}.get(
    platform.system(), 'Noto Sans CJK TC')
_installed = False


def install_theme():
    """Set CTk's documented theme defaults once, before creating widgets."""
    global _installed
    import customtkinter as ctk
    if _installed:
        return
    ctk.set_default_color_theme('blue')
    theme = ctk.ThemeManager.theme
    for name in ('CTk', 'CTkToplevel'):
        theme[name]['fg_color'] = BACKGROUND
    theme['CTkFrame'].update(fg_color=CARD, top_fg_color=SURFACE,
                             border_color=BORDER, corner_radius=12)
    theme['CTkLabel']['text_color'] = TEXT
    theme['CTkButton'].update(fg_color=ACCENT, hover_color=HOVER,
                              border_color=BORDER, corner_radius=8)
    for name in ('CTkEntry', 'CTkComboBox', 'CTkTextbox'):
        theme[name].update(fg_color=CARD, border_color=BORDER, text_color=TEXT)
    theme['CTkEntry'].update(border_width=1, placeholder_text_color=MUTED)
    theme['CTkProgressBar'].update(fg_color=SURFACE, progress_color=ACCENT)
    for name in ('CTkCheckBox', 'CTkRadioButton'):
        theme[name].update(fg_color=ACCENT, hover_color=HOVER, text_color=TEXT)
    theme['CTkOptionMenu'].update(fg_color=ACCENT, button_color=HOVER)
    theme['CTkFont'].update(family=FONT_FAMILY, size=13)
    _installed = True


def ui_font(*, size=13, family=None, **kwargs):
    import customtkinter as ctk
    # Keep intentionally monospaced timecodes and raw editors; CTk/Tk provide
    # CJK glyph fallback there. Small controls still get a readable caption.
    return ctk.CTkFont(family=family or FONT_FAMILY, size=max(12, size), **kwargs)


def wrap_to_width(label, *, padding=0):
    """Wrap paths/messages to the allocated width, never their requested width."""
    import tkinter as tk
    last_width = None
    def resize(event):
        nonlocal last_width
        scale = label._get_widget_scaling()
        width = max(40, int(event.width / scale - padding))
        if width != last_width:
            last_width = width
            label.configure(wraplength=width)
    # CTkLabel.bind targets both its text label and canvas. Those have
    # different widths and would recursively resize each other when scaled.
    # Observe only the outer native frame's allocated geometry.
    tk.Misc.bind(label, '<Configure>', resize, add='+')
