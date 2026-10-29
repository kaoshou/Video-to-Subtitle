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
    # Selection fields are quieter than primary actions.
    theme['CTkOptionMenu'].update(fg_color=SURFACE, button_color=SURFACE,
                                  button_hover_color=BORDER, text_color=TEXT)
    theme['CTkFont'].update(family=FONT_FAMILY, size=13)
    _installed = True


def secondary_button_style():
    """Shared low-emphasis actions, with readable light/dark states."""
    return dict(fg_color=SURFACE, hover_color=BORDER, text_color=TEXT,
                border_width=1, border_color=BORDER, corner_radius=8)


class HoverHint:
    """A short, delayed hint for pointer and keyboard focus."""
    def __init__(self, widget, text):
        self.widget, self.text = widget, text
        self.timer = self.window = None
        widget.bind('<Enter>', self.schedule, add='+')
        widget.bind('<FocusIn>', self.schedule, add='+')
        for event in ('<Leave>', '<FocusOut>', '<ButtonPress>', '<Destroy>'):
            widget.bind(event, self.hide, add='+')

    def schedule(self, event=None):
        self.hide()
        self.timer = self.widget.after(500, self.show)

    def show(self):
        import customtkinter as ctk
        self.timer = None
        if not self.widget.winfo_exists():
            return
        self.window = ctk.CTkToplevel(self.widget)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.transient(self.widget.winfo_toplevel())
        ctk.CTkLabel(self.window, text=self.text, font=ui_font(size=12),
                     fg_color=SURFACE, corner_radius=6).pack(padx=1, pady=1)
        self.window.update_idletasks()
        x = min(self.widget.winfo_rootx(), self.widget.winfo_screenwidth() - self.window.winfo_reqwidth() - 8)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        if y + self.window.winfo_reqheight() > self.widget.winfo_screenheight():
            y = self.widget.winfo_rooty() - self.window.winfo_reqheight() - 5
        self.window.geometry(f'+{max(0, x)}+{max(0, y)}')
        self.window.deiconify()

    def hide(self, event=None):
        if self.timer is not None:
            self.widget.after_cancel(self.timer)
            self.timer = None
        if self.window is not None:
            self.window.destroy()
            self.window = None


def attach_placeholder(entry, variable, text):
    """CTk's built-in placeholder is inactive with a textvariable.

    Paint a hint over an empty field, without inserting it into user data.
    """
    import customtkinter as ctk
    entry.configure(placeholder_text=text)
    hint = ctk.CTkLabel(entry, text=text, anchor='w', height=20,
                        font=entry.cget('font'), text_color=MUTED,
                        fg_color=entry.cget('fg_color'), corner_radius=0)

    def refresh(*_):
        if variable.get() or entry._entry.focus_get() == entry._entry:
            hint.place_forget()
        else:
            hint.place(relx=.035, rely=.5, relwidth=.93, anchor='w')

    token = variable.trace_add('write', refresh)
    entry.bind('<FocusIn>', lambda event: hint.place_forget(), add='+')
    entry.bind('<FocusOut>', refresh, add='+')
    entry.bind('<Destroy>', lambda event: variable.trace_remove('write', token), add='+')
    hint.bind('<Button-1>', lambda event: entry.focus_set())
    refresh()
    return hint


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
