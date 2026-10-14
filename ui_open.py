"""Open an exported local player, preserving its actual filename on Windows."""
import os
from pathlib import Path
import sys
import webbrowser
from tkinter import messagebox


def open_local_page(path, *, parent=None):
    """Use Windows' file association, not the handler for a file:// URL.

    No shell commands or browser-specific executables: spaces, Unicode, #
    and percent signs remain literal parts of the exported filename.
    """
    try:
        target = Path(path).absolute()
        if not target.is_file():
            raise FileNotFoundError(f'找不到網頁檔案：{target}')
        if sys.platform == 'win32':
            os.startfile(str(target))
        elif not webbrowser.open_new_tab(target.as_uri()):
            raise OSError(f'預設瀏覽器未接受網頁：{target}')
    except (OSError, ValueError, TypeError) as error:
        messagebox.showerror('無法開啟網頁',
                             f'{error}\n\n請確認網頁檔案仍存在，且已設定預設網頁瀏覽器。',
                             parent=parent)
        return False
    return True
