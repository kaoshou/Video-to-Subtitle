"""Native mapping contract: child layout must finish before its first Map."""
import os
import unittest


@unittest.skipUnless(os.environ.get('VTS_RUN_GUI_TESTS') == '1', 'requires native GUI session')
class DialogVisibilityTests(unittest.TestCase):
    def test_scrollbar_draw_cannot_reenter_while_flushing_idle_layout(self):
        import customtkinter as ctk
        from unittest.mock import patch
        from ui_flow import AutoHideScrollableFrame
        from ui_windows import DialogWindow
        root = ctk.CTk()
        self.addCleanup(root.destroy)
        child = DialogWindow(root)
        frame = AutoHideScrollableFrame(child)
        frame.pack()
        child.update_idletasks()
        def redraw(*args):
            frame._update_scrollbar()
            child.update_idletasks()
        with patch.object(frame._scrollbar, 'set', side_effect=redraw) as setter:
            frame._scroll_fractions = None
            frame._update_scrollbar()
            child.update_idletasks()
            self.assertEqual(setter.call_count, 1)
        child.destroy()

    def test_layout_remains_hidden_until_positioned_and_mapped_once(self):
        import customtkinter as ctk
        from ui_windows import DialogWindow, show_dialog
        root = ctk.CTk()
        self.addCleanup(root.destroy)
        root.geometry('900x700+120+80')
        root.update()
        child = DialogWindow(root)
        mappings = []
        child.bind('<Map>', lambda event: mappings.append(child.geometry()) if event.widget == child else None, add='+')
        ctk.CTkLabel(child, text='測試內容').pack()
        child.update_idletasks()
        self.assertEqual(child.state(), 'withdrawn')
        self.assertFalse(child.winfo_ismapped())
        self.assertEqual(mappings, [])
        show_dialog(child, root, 400, 300)
        root.update()
        self.assertEqual(len(mappings), 1)
        self.assertGreater(child.winfo_rootx(), root.winfo_rootx())
        self.assertGreater(child.winfo_rooty(), root.winfo_rooty())
        child.destroy()
