"""Compact native toolbars that wrap without shrinking their controls."""
import math
import tkinter as tk
import customtkinter as ctk


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
        key = (width, tuple(sizes))
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
