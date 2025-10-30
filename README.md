import tkinter as tk
from tkinter import filedialog, messagebox
import os

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YourMusicLibrary")
        
        # UI layout creation
        self.label = tk.Label(self, text="Music Library Manager")
        self.label.pack(pady=10)
        self.open_btn = tk.Button(self, text="Open Library", command=self.open_library)
        self.open_btn.pack(pady=5)
        self.quit_btn = tk.Button(self, text="Quit", command=self.quit)
        self.quit_btn.pack(pady=5)

        # ---- Laptop-friendly window size (~55% of screen) ----
        try:
            self.update_idletasks()
            sw = int(self.winfo_screenwidth())
            sh = int(self.winfo_screenheight())
            # target size ~55% of screen with sensible minimums
            tw = max(800, int(sw * 0.55))
            th = max(600, int(sh * 0.55))
            # center the window
            x = max(0, (sw - tw) // 2)
            y = max(22, (sh - th) // 5)
            self.minsize(720, 520)
            self.geometry(f"{tw}x{th}+{x}+{y}")
        except Exception:
            pass

    def open_library(self):
        # Open directory dialog
        targetFolder = filedialog.askdirectory(title="Select Music Library Folder")
        if not targetFolder:
            return
        
        # Compute desired Finder window bounds: about half of the app size, placed below the app
        try:
            self.update_idletasks()
            app_x = int(self.winfo_rootx())
            app_y = int(self.winfo_rooty())
            app_w = int(self.winfo_width())
            app_h = int(self.winfo_height())
            screen_w = int(self.winfo_screenwidth())
            screen_h = int(self.winfo_screenheight())
            margin = 8
            # scale finder window to ~50% of the app size
            win_w = max(420, min(int(app_w * 0.5), screen_w - 40))
            win_h = max(320, min(int(app_h * 0.5), screen_h - 80))
            # align left with app, place under app
            x1 = max(0, min(app_x, screen_w - win_w - 20))
            y1 = max(22, min(app_y + app_h + margin, screen_h - win_h - 40))
            x2 = x1 + win_w
            y2 = y1 + win_h
        except Exception:
            # Fallback bounds if geometry unavailable
            x1, y1, x2, y2 = 120, 120, 720, 520
        
        # Remaining logic to toggle Finder window ID, create new Finder window, etc.
        # (unchanged)
        # ... (not shown here)

        messagebox.showinfo("Library Opened", f"Opened library at: {targetFolder}")

if __name__ == "__main__":
    app = App()
    app.mainloop()
