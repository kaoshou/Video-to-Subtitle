"""Optional native file DnD shared by the desktop's converter windows."""


def dropped_paths(widget, data):
    """Decode a Tcl file list without corrupting spaces or literal braces."""
    import tkinter as tk
    try:
        return tuple(widget.tk.splitlist(data))
    except (tk.TclError, TypeError):
        return ()


def register_file_drop(surface, callback):
    """Register actual child surfaces, including CTk's internal Tk controls.

    A toplevel alone is insufficient on native platforms where the child under
    the pointer owns the drop. Safe to call again after rendering new rows.
    """
    import tkinter as tk
    try:
        from tkinterdnd2 import DND_FILES, TkinterDnD
        root = surface._root()
        if not root.tk.call('info', 'commands', 'tkdnd::drop_target'):
            root.TkdndVersion = TkinterDnD._require(root)
        def attach(widget):
            if not getattr(widget, '_vts_file_drop_bound', False):
                TkinterDnD.DnDWrapper.drop_target_register(widget, DND_FILES)
                TkinterDnD.DnDWrapper.dnd_bind(widget, '<<Drop>>', callback)
                widget._vts_file_drop_bound = True
            for child in widget.winfo_children():
                attach(child)
        attach(surface)
        return True
    except (ImportError, OSError, RuntimeError, tk.TclError):
        return False
