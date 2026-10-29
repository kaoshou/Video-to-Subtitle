"""Compact native toolbars that wrap without shrinking their controls."""
import math
import tkinter as tk
import customtkinter as ctk


class AutoHideScrollableFrame(ctk.CTkScrollableFrame):
    """Keep scrolling available, showing its bar only for overflowing content."""
    def __init__(self, master, **kwargs):
        self._scroll_check = None
        super().__init__(master, **kwargs)
        self._bar_colors = (self._scrollbar.cget('button_color'),
                            self._scrollbar.cget('button_hover_color'))
        self._parent_canvas.configure(yscrollcommand=self._update_scrollbar)
        self._parent_canvas.bind('<Configure>', self._update_scrollbar, add='+')
        self._update_scrollbar()

    def _update_scrollbar(self, *args):
        # Tk can queue scroll fractions from an earlier geometry. Wait for
        # layout, then measure the current content/viewport instead of using
        # stale callback fractions to decide whether scrolling is necessary.
        if self._scroll_check is None:
            self._scroll_check = self.after_idle(self._sync_scrollbar)

    def _sync_scrollbar(self):
        self._scroll_check = None
        self._scrollbar.set(*self._parent_canvas.yview())
        # Keep geometry stable: unmapping CTk's scaled scrollbar can leave a
        # native macOS drawing artifact. Blend the full-range bar into its
        # background instead; restore both normal/hover colors on overflow.
        bounds = self._parent_canvas.bbox('all')
        overflow = bool(bounds and bounds[3] - bounds[1] > self._parent_canvas.winfo_height())
        background = self.cget('fg_color')
        normal, hover = self._bar_colors if overflow else (background, background)
        self._scrollbar.configure(fg_color=background, button_color=normal,
                                  button_hover_color=hover)

    def destroy(self):
        if self._scroll_check is not None:
            self.after_cancel(self._scroll_check)
            self._scroll_check = None
        super().destroy()


class FlowToolbar(ctk.CTkFrame):
    def __init__(self, master, *, gap=6, **kwargs):
        super().__init__(master, fg_color='transparent', height=1, **kwargs)
        self._items = []
        self._gap = gap
        self._pending_layout = None
        self._layout_key = None
        tk.Misc.bind(self, '<Configure>', lambda event: self.request_layout(), add='+')

    def add(self, widget):
        self._items.append(widget)
        # Font/scaling changes can reach children after the toolbar's own
        # Configure event. Placed children do not propagate requested sizes.
        tk.Misc.bind(widget, '<Configure>', lambda event: self.request_layout(), add='+')
        self.request_layout()
        return widget

    def request_layout(self):
        if self._pending_layout is None:
            self._pending_layout = self.after_idle(self._layout_items)

    def _layout_items(self):
        self._pending_layout = None
        scale = self._get_widget_scaling()
        width = int(self.winfo_width() / scale)
        if width <= 1:
            return
        sizes = [(math.ceil(item.winfo_reqwidth() / scale),
                  math.ceil(item.winfo_reqheight() / scale)) for item in self._items]
        key = (scale, width, tuple(sizes))
        if key == self._layout_key:
            return
        self._layout_key = key
        x = y = row_height = 0
        for item, (item_width, item_height) in zip(self._items, sizes):
            if x and x + item_width > width:
                x = 0
                y += row_height + self._gap
                row_height = 0
            item.place(x=x, y=y)
            x += item_width + self._gap
            row_height = max(row_height, item_height)
        self.configure(height=max(1, y + row_height))

    def destroy(self):
        if self._pending_layout is not None:
            self.after_cancel(self._pending_layout)
            self._pending_layout = None
        super().destroy()
