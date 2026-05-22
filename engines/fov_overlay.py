"""
FOV Overlay — transparent click-through circle showing the aim FOV area.
Ported from Unibot screen.py FovOverlay class.
"""

import threading
import os

try:
    import tkinter as tk
    import win32con
    import win32gui
except Exception:
    tk = None
    win32con = None
    win32gui = None


class FovOverlay:
    TRANSPARENT_COLOR = '#ff00ff'
    TRANSPARENT_COLORREF = 0x00FF00FF
    CIRCLE_COLOR = '#ffff00'

    def __init__(self, screen, aim_fov, config=None):
        self.screen = screen
        self.aim_fov = aim_fov
        self.config = config
        self.canvas = None
        self.circle_id = None
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        if tk is None or win32gui is None or win32con is None:
            return

        root = None
        try:
            root = tk.Tk()
            root.overrideredirect(True)
            root.configure(bg=self.TRANSPARENT_COLOR)
            root.attributes('-topmost', True)
            root.attributes('-transparentcolor', self.TRANSPARENT_COLOR)
            root.geometry(f'{self.screen[0]}x{self.screen[1]}+0+0')

            canvas = tk.Canvas(
                root,
                width=self.screen[0],
                height=self.screen[1],
                bg=self.TRANSPARENT_COLOR,
                highlightthickness=0,
                bd=0
            )
            canvas.pack(fill='both', expand=True)
            self.canvas = canvas

            self.draw_circle()

            root.update_idletasks()
            root.update()
            self.make_click_through(root.winfo_id())
            self.keep_alive(root)
            root.mainloop()
        except Exception:
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass

    def keep_alive(self, root):
        if self.stop_event.is_set():
            root.destroy()
            return

        try:
            root.lift()
            root.attributes('-topmost', True)
        except Exception:
            pass
        self.refresh_from_config()
        root.after(250, lambda: self.keep_alive(root))

    def draw_circle(self):
        if self.canvas is None:
            return

        center_x = self.screen[0] // 2
        center_y = self.screen[1] // 2
        radius = int(min(self.aim_fov[0], self.aim_fov[1]))

        if self.circle_id is None:
            self.circle_id = self.canvas.create_oval(
                center_x - radius,
                center_y - radius,
                center_x + radius,
                center_y + radius,
                outline=self.CIRCLE_COLOR,
                width=2
            )
        else:
            self.canvas.coords(
                self.circle_id,
                center_x - radius,
                center_y - radius,
                center_x + radius,
                center_y + radius
            )

    def refresh_from_config(self):
        if self.config is None:
            return

        vision = self.config.get('vision', {})
        aim_fov = (
            vision.get('aim_fov_x', self.aim_fov[0]),
            vision.get('aim_fov_y', self.aim_fov[1])
        )
        if aim_fov == self.aim_fov:
            return

        self.aim_fov = aim_fov
        self.draw_circle()

    @staticmethod
    def make_click_through(hwnd):
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        style |= (
            win32con.WS_EX_LAYERED |
            win32con.WS_EX_TRANSPARENT |
            win32con.WS_EX_TOPMOST |
            win32con.WS_EX_TOOLWINDOW
        )
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style)
        win32gui.SetLayeredWindowAttributes(
            hwnd,
            FovOverlay.TRANSPARENT_COLORREF,
            0,
            win32con.LWA_COLORKEY
        )

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=0.5)
