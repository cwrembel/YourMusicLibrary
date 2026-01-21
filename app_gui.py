import os, sys, json, time, threading, subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# --- Watchdog & Library index imports ---
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from hashing import hash_robust as berechne_audio_hash
from kopiere_einzigartige import index_path, load_index, save_index, AUDIO_EXTS

APP_DIR = os.path.dirname(__file__)
CFG_PATH = os.path.join(APP_DIR, "app_config.json")
SCRIPT_PATH = os.path.join(APP_DIR, "kopiere_einzigartige.py")

DEFAULT_LIBRARY = os.path.join(APP_DIR, "Musik Library")
MAX_RECENT = 12

# Finder opening behavior: set to True to position Finder next to the app (may cause slight macOS window jitter)
POSITION_FINDER = False

# --- Source Combo constants ---
PLACEHOLDER_SRC = "Click to choose source"
CLEAR_LABEL = "— Clear selection —"

def load_cfg():
    if os.path.exists(CFG_PATH):
        try:
            with open(CFG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "library": DEFAULT_LIBRARY,
        "alt_library": "",
        "use_alt": False,
        "sources": [""]*6,
        "recent_sources": [],
        "recent_targets": [],
        "delete_warn_suppressed": [False]*6,   # NEW
        "delete_warn_suppressed_global": False,  # NEW: one switch for all sources
    }


def save_cfg(cfg):
    cfg["recent_sources"] = cfg.get("recent_sources", [])[:MAX_RECENT]
    cfg["recent_targets"] = cfg.get("recent_targets", [])[:MAX_RECENT]
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def add_recent(lst, path):
    if not path: return lst
    lst = [p for p in lst if p != path]
    lst.insert(0, path)
    return lst[:MAX_RECENT]


class LibraryWatcher(FileSystemEventHandler):
    def __init__(self, target_dir):
        super().__init__()
        self.target = os.path.abspath(target_dir)
        self.index_file = index_path(target_dir)
        self.hashes = load_index(self.index_file)
        self.map_file = os.path.join(target_dir, ".hash_map.json")
        self._load_map()

    def _load_map(self):
        try:
            if os.path.exists(self.map_file):
                with open(self.map_file, "r", encoding="utf-8") as f:
                    self.path_map = json.load(f)
            else:
                self.path_map = {}
        except Exception:
            self.path_map = {}

    def _save_map(self):
        try:
            tmp = self.map_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.path_map, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.map_file)
        except Exception:
            pass

    def _is_audio(self, path):
        ext = os.path.splitext(path)[1].lower()
        return ext in AUDIO_EXTS

    def _within_library(self, path):
        try:
            return os.path.commonpath([self.target, os.path.abspath(path)]) == self.target
        except Exception:
            return False

    # Removed on_created: no hash calculations or map updates on create

    def on_deleted(self, event):
        if event.is_directory:
            return
        p = event.src_path
        if p in self.path_map:
            h = self.path_map.pop(p)
            if h in self.hashes:
                self.hashes.remove(h)
                save_index(self.index_file, self.hashes)
            self._save_map()

    def on_moved(self, event):
        if event.is_directory:
            return
        src_in = self._within_library(event.src_path)
        dst_in = self._within_library(event.dest_path)
        # Case 1: moved out of library -> remove hash and map entry
        if src_in and not dst_in:
            p = event.src_path
            if p in self.path_map:
                h = self.path_map.pop(p)
                if h in self.hashes:
                    self.hashes.remove(h)
                    save_index(self.index_file, self.hashes)
                self._save_map()
            return
        # Case 2: internal move/rename -> update map path, keep hash
        if src_in and dst_in:
            p_src = event.src_path
            p_dst = event.dest_path
            if p_src in self.path_map:
                self.path_map[p_dst] = self.path_map.pop(p_src)
                self._save_map()
            return
        # Ignore moves from outside into library (no hash calculation)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YourMusicLibrary")
        self.minsize(920, 560)
        # Start hidden to avoid the initial jump before centering
        self.withdraw()

        self._finder_win_id = None  # remember Finder window id we opened
        # --- Menu bar ---
        menubar = tk.Menu(self)

        warnings_menu = tk.Menu(menubar, tearoff=0)
        warnings_menu.add_command(
        label="Reset ‘Delete after transfer’ confirmations…",
        command=self.reset_delete_warnings
        )

        menubar.add_cascade(label="Warnings", menu=warnings_menu)
        self.config(menu=menubar)

        # --- end menu ---
        self.cfg = load_cfg()
        self.cfg.setdefault("delete_warn_suppressed", [False]*6)
        if len(self.cfg["delete_warn_suppressed"]) != 6:
            self.cfg["delete_warn_suppressed"] = [False]*6
        self.cfg.setdefault("delete_warn_suppressed_global", False)
        # Always start with empty sources and no recent source list
        self.cfg["sources"] = [""] * 6
        self.cfg["recent_sources"] = []
        
        # State
        self.library_var = tk.StringVar(value=self.cfg.get("library", DEFAULT_LIBRARY))
        self.use_alt_var = tk.BooleanVar(value=self.cfg.get("use_alt", False))
        self.alt_library_var = tk.StringVar(value=self.cfg.get("alt_library", ""))
        # Force default on startup: always start with Main (Path Music Library)
        self.use_alt_var.set(False)
        self.cfg["use_alt"] = False  # ensure it saves back as default
        # Source variables with placeholder text
        self.source_vars = [tk.StringVar(value=PLACEHOLDER_SRC) for _ in range(6)]        
        self.source_delete_vars = [tk.BooleanVar(value=False) for _ in range(6)]

        # ---------- Layout ----------
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        # Main Library Row (Top)
        top = ttk.LabelFrame(root)
        top.pack(fill="x")
        top_grid = ttk.Frame(top); top_grid.pack(fill="x", padx=8, pady=6)

        # --- Big centered 'Open Library' button above the path ---
        style = ttk.Style(self)
        try:
            style.configure("Big.TButton", padding=(18, 12), font=("Helvetica", 14, "bold"))
        except Exception:
            style.configure("Big.TButton", padding=(18, 12))  # fallback if font not available

        open_btn = ttk.Button(top_grid, text="Music Library", style="Big.TButton", command=self.open_library)
        open_btn.grid(row=0, column=0, columnspan=3, sticky="n", pady=(0,6))

        # Insert label above the combobox
        ttk.Label(top_grid, text="Music Library Path").grid(row=1, column=0, columnspan=3, sticky="w", pady=(0,4))

        # Path combobox one row below the label, full width — with highlight wrapper
        self.library_wrap = tk.Frame(top_grid, bg="#DFF5D8")  # greenish highlight when active
        self.library_wrap.grid(row=2, column=0, columnspan=3, sticky="we")
        self.library_combo = ttk.Combobox(self.library_wrap, width=90, textvariable=self.library_var,        
                                          values=self.cfg.get("recent_targets", []))
        self.library_combo.pack(fill="x", padx=6, pady=6)        
        # open dialog when clicking on the text area, keep arrow to show recent list
        self._bind_combo_open_dialog(self.library_combo, lambda: self._browse_library())

        # make all three columns share width so the button centers nicely
        top_grid.grid_columnconfigure(0, weight=1)
        top_grid.grid_columnconfigure(1, weight=1)
        top_grid.grid_columnconfigure(2, weight=1)

        # Sources Grid (2 rows x 3 cols)
        mid = ttk.LabelFrame(root)
        mid.pack(fill="x", pady=(10,0))

        src_grid = ttk.Frame(mid); src_grid.pack(fill="x", padx=8, pady=6)
        self.source_combos = []
        self.source_wraps = []
        for i in range(6):
            col = i % 3
            row = i // 3
            cell = ttk.Frame(src_grid, padding=6)
            cell.grid(row=row, column=col, sticky="we", padx=4, pady=4)
            ttk.Label(cell, text=f"Source {i+1}").grid(row=0, column=0, sticky="w")
            
            # colored wrapper for the source combobox (lets us switch green/red)
            wrap = tk.Frame(cell, bg="#DFF5D8")  # default green on startup
            wrap.grid(row=1, column=0, columnspan=2, sticky="we")
            combo = ttk.Combobox(wrap, width=40, textvariable=self.source_vars[i], values=[], state="readonly")                
            combo.pack(fill="x", padx=6, pady=6)
            # refresh the dropdown just before it opens; handle selection from the list
            try:
                combo.configure(postcommand=lambda idx=i: self._refresh_combo_values(idx))
            except Exception:
                pass
            combo.bind("<<ComboboxSelected>>", lambda e, idx=i: self._on_source_selected(idx))

            # keep references
            self.source_wraps.append(wrap)
            self._bind_combo_open_dialog(combo, lambda idx=i: self._browse_source(idx))
            self.source_combos.append(combo)
           
            # Delete-after checkbox
            ttk.Checkbutton(cell, text="Delete files from source after transfer",
                            variable=self.source_delete_vars[i],
                            command=lambda idx=i: self.on_delete_toggle(idx)
                            ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6,0))
            cell.grid_columnconfigure(0, weight=1)

        for c in range(3):
            src_grid.grid_columnconfigure(c, weight=1)

        # ensure placeholders are visible
        for v in self.source_vars:
            if not v.get().strip():
                v.set(PLACEHOLDER_SRC)


        # Alternative target
        alt = ttk.Frame(root, padding=(0,8,0,0))
        alt.pack(fill="x")
        ttk.Checkbutton(alt, text="Alternative target", variable=self.use_alt_var,
                        command=self.update_arrows).pack(side="left")
        # wrap the alt combobox to allow colored highlight
        self.alt_wrap = tk.Frame(alt, bg="#EEEEEE")
        self.alt_wrap.pack(side="left", fill="x", expand=True, padx=(8,8))
        self.alt_combo = ttk.Combobox(self.alt_wrap, width=60, textvariable=self.alt_library_var,       
                                      values=self.cfg.get("recent_targets", []), state="disabled")
        self.alt_combo.pack(fill="x", padx=6, pady=6)  
        # open dialog when clicking on the text area, keep arrow to show recent list
        self._bind_combo_open_dialog(self.alt_combo, lambda: self._browse_alt())

        # Bottom controls
        bottom = ttk.Frame(root, padding=(0,8,0,0))
        bottom.pack(fill="x")
        self.start_btn = ttk.Button(bottom, text="Start / Merge", command=self.start_merge)
        self.start_btn.pack()

        # Inline status strip (progress + ETA) directly under the app
        # - starts as "indeterminate" (pulsing) until we see first progress tick
        self._inline_pulsing = False  # internal flag

        # Thicker, more visible progress bar
        try:
            s = ttk.Style(self)
            s.configure("Inline.Horizontal.TProgressbar", thickness=10)
            bar_style = "Inline.Horizontal.TProgressbar"
        except Exception:
            bar_style = "Horizontal.TProgressbar"

        self.inline_frame = ttk.Frame(root, padding=(10,6,10,10))
        self.inline_frame.pack(fill="x")
        self.inline_bar = ttk.Progressbar(self.inline_frame, mode="indeterminate",
                                          maximum=1, style=bar_style)
        self.inline_bar.pack(fill="x")
        # Row with percentage (left) and ETA (right)
        info_row = ttk.Frame(self.inline_frame)
        info_row.pack(fill="x")
        self.inline_pct = ttk.Label(info_row, text="0%", anchor="w")
        self.inline_pct.pack(side="left")
        self.inline_eta = ttk.Label(info_row, text="ETA: —")
        self.inline_eta.pack(side="right")
        self.running = False

        self.update_alt_controls()
        self.update_arrows()
        self.update_target_highlight()
        # --- center main window on screen (show only after geometry is set) ---
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        # now show without jumping
        self.deiconify()
        self.lift()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        # Start library folder watcher (background thread)
        # try:
        #     self.library_observer = Observer()
        #     self.library_watcher = LibraryWatcher(self.library_var.get())
        #     self.library_observer.schedule(self.library_watcher, path=self.library_var.get(), recursive=True)
        #     self.library_observer.start()
        # except Exception as e:
        #     print("Watcher could not start:", e)
        # Auto-check: Ziel leer + Index vorhanden? → Reset anbieten
        self.after(200, lambda: self._maybe_reset_index(self.library_var.get().strip()))

    # ---------- UI helpers ----------
    def _bring_app_front(self):
        try:
            self.lift()
            self.focus_force()
            # temporarily make window topmost to win z-order, then release
            try:
                self.attributes("-topmost", True)
                self.after(200, lambda: self.attributes("-topmost", False))
            except Exception:
                pass
        except Exception:
            pass

    def open_library(self):
        # Path from the combobox (Music Library Path)
        path = self.library_combo.get().strip()
        if not path:
            return
        # --- Windows handling ---    
        if sys.platform.startswith("win"):
            if not os.path.isdir(path):
                messagebox.showwarning("Folder not found", f"The folder does not exist:\n{path}")   
                return 
            try:
                os.startfile(os.path.abspath(path))
            except Exception as e:
                messagebox.showerror("Error", f"Could not open folder:\n\n{path}\n\nError: {e}")
            return

        # macOS Finder handling
        if not os.path.isdir(path):
            messagebox.showerror(
                "Folder not found",
                f"The folder does not exist:\n\n{path}"
            )
            return
        try:
            p = os.path.abspath(path)
            p_slash = p if p.endswith('/') else p + '/'
            p_esc = p.replace('"', '\\"')
            p_slash_esc = p_slash.replace('"', '\\"')

            # If we previously opened a Finder window, try to close that exact window by id
            if self._finder_win_id is not None:
                script_close = (
                    'tell application "Finder"\n'
                    '    try\n'
                    '        if exists (window id {wid}) then\n'
                    '            close (window id {wid})\n'
                    '            return "CLOSED_BY_ID"\n'
                    '        end if\n'
                    '    end try\n'
                    '    return "NO_ID"\n'
                    'end tell\n'
                ).format(wid=int(self._finder_win_id))
                rc = subprocess.run(["osascript", "-e", script_close], capture_output=True, text=True)
                out = (rc.stdout or "").strip()
                if out == "CLOSED_BY_ID":
                    self._finder_win_id = None
                    # Ensure our app stays in front (Finder stays visible behind)
                    self.after(10, self._bring_app_front)
                    return
                # if NO_ID -> fall through and open a fresh window

            # Compute desired Finder window bounds: centered on screen
            try:
                self.update_idletasks()
                screen_w = int(self.winfo_screenwidth())
                screen_h = int(self.winfo_screenheight())

                # Size of the Finder window (reasonable defaults)
                win_w = min(900, max(500, screen_w - 200))
                win_h = min(650, max(400, screen_h - 200))

                x1 = max(0, (screen_w - win_w) // 2)
                y1 = max(22, (screen_h - win_h) // 2)  # keep below menu bar
                x2 = x1 + win_w
                y2 = y1 + win_h
            except Exception:
                # Fallback bounds if geometry unavailable
                x1, y1, x2, y2 = 100, 120, 900, 650

            # Open a new Finder window for the folder and return its window id, positioned below the app
            script_open = (
                'tell application "Finder"\n'
                '    activate\n'
                '    set targetFolder to POSIX file "{p}" as alias\n'
                '    set newWin to (make new Finder window to targetFolder)\n'
                '    set bounds of newWin to {{{x1}, {y1}, {x2}, {y2}}}\n'
                '    set index of newWin to 1\n'
                '    return (id of newWin) as string\n'
                'end tell\n'
            ).format(p=p_esc, x1=x1, y1=y1, x2=x2, y2=y2)
            rc2 = subprocess.run(["osascript", "-e", script_open], capture_output=True, text=True)
            win_id_txt = (rc2.stdout or "").strip()
            try:
                self._finder_win_id = int(win_id_txt)
            except Exception:
                self._finder_win_id = None
        except Exception as e:
            print("Could not toggle Finder window:", e)

    def pick_library(self):
        d = filedialog.askdirectory(initialdir=self.library_var.get() or APP_DIR, title="Select Main Library")
        if d:
            self.library_var.set(d)
            self.cfg["recent_targets"] = add_recent(self.cfg.get("recent_targets", []), d)
            self.library_combo["values"] = self.cfg["recent_targets"]
            self.update_arrows()
            self._maybe_reset_index(d)

    def pick_alt(self):
        d = filedialog.askdirectory(initialdir=self.alt_library_var.get() or APP_DIR, title="Select Alternative Library")
        if d:
            self.alt_library_var.set(d)
            self.cfg["recent_targets"] = add_recent(self.cfg.get("recent_targets", []), d)
            self.alt_combo["values"] = self.cfg["recent_targets"]
            self.update_arrows()
            # If alternative is active: offer index reset (empty target + index present)
            try:
                if self.use_alt_var.get():
                    self._maybe_reset_index(d)
            except Exception:
                pass

    def pick_source(self, idx:int):
        d = filedialog.askdirectory(initialdir=self.source_vars[idx].get() or "/", title=f"Select Source {idx+1}")
        if d:
            self.source_vars[idx].set(d)
            self.cfg["recent_sources"] = add_recent(self.cfg.get("recent_sources", []), d)
            # Update all dropdowns
            for cb in self.source_combos:
                cb["values"] = self.cfg["recent_sources"]

    # --- Folder browsing handlers ---
    def _browse_library(self, event=None):
        d = filedialog.askdirectory(initialdir=self.library_var.get() or APP_DIR, title="Select Main Library")
        if d:
            self.library_var.set(d)
            self.cfg["recent_targets"] = add_recent(self.cfg.get("recent_targets", []), d)
            self.library_combo["values"] = self.cfg["recent_targets"]
            self.update_arrows()
            self._maybe_reset_index(d)
        return "break"  # prevents combo from also opening

    def _browse_alt(self, event=None):
        # only if Alternative target is active
        if not self.use_alt_var.get():
            return "break"
        d = filedialog.askdirectory(initialdir=self.alt_library_var.get() or APP_DIR, title="Select Alternative Library")
        if d:
            self.alt_library_var.set(d)
            self.cfg["recent_targets"] = add_recent(self.cfg.get("recent_targets", []), d)
            self.alt_combo["values"] = self.cfg["recent_targets"]
            self.update_arrows()
            # If alternative is active: offer index reset (empty target + index present)
            try:
                if self.use_alt_var.get():
                    self._maybe_reset_index(d)
            except Exception:
                pass
        return "break"

    def _browse_source(self, idx, event=None):
        d = filedialog.askdirectory(initialdir=self._normalized_src(self.source_vars[idx].get()) or "/", title=f"Select Source {idx+1}")       
        if d:
            self._set_source_path(idx, d)
        return "break"            

    def _bind_combo_open_dialog(self, combo, handler):
        """
        Binds a click on the combobox text area to open the folder dialog,
        but keeps the right-side drop-down arrow working to show the recent list.
        """
        def on_click(event):
            try:
                # Approximate width of the drop-down arrow area (in pixels)
                drop_w = 24
                if event.x >= combo.winfo_width() - drop_w:
                    # Click on the arrow -> keep default behavior (show recent list)
                    return
                handler()
                return "break"
            except Exception:
                # Fallback to default behavior
                return

        combo.bind("<Button-1>", on_click)
        # Keyboard shortcuts to open dialog
        combo.bind("<Key-Return>", lambda e: (handler(), "break"))
        try:
            # macOS-like shortcut: Cmd+O to open
            combo.bind("<Command-o>", lambda e: (handler(), "break"))
        except Exception:
            pass

    def _normalized_src(self, val: str) -> str:
        val = (val or "").strip()
        return "" if (not val or val == PLACEHOLDER_SRC or val == CLEAR_LABEL) else val

    def _current_sources(self, exclude_idx: int | None = None) -> set[str]:
        used = set()
        for i, v in enumerate(self.source_vars):
            if exclude_idx is not None and i == exclude_idx:
                continue
            p = self._normalized_src(v.get())
            if p:
                used.add(p)
        return used

    def _refresh_combo_values(self, idx: int):
        """Populate the dropdown with a 'Clear' option and recent sources not already used."""
        used = self._current_sources(exclude_idx=idx)
        recents = [p for p in self.cfg.get("recent_sources", []) if p and p not in used and os.path.isdir(p)]
        values = [CLEAR_LABEL] + recents
        try:
            self.source_combos[idx]["values"] = values
        except Exception:
            pass

    def _set_source_path(self, idx: int, path: str):
        """Set source path with duplicate check and recents update; placeholder if empty."""
        if not path:
            self.source_vars[idx].set(PLACEHOLDER_SRC)
            try:
                cb = self.source_combos[idx]
                cb.set(PLACEHOLDER_SRC)
                cb.selection_clear()
                cb.icursor('end')
                self.after_idle(lambda: cb.master.focus_set())
            except Exception:
                pass
            return
        # prevent duplicates across slots
        if path in self._current_sources(exclude_idx=idx):
            messagebox.showwarning("Duplicate", "This folder is already selected in another source.")
            self.source_vars[idx].set(PLACEHOLDER_SRC)
            return
        # accept
        self.source_vars[idx].set(path)
        self.cfg["recent_sources"] = add_recent(self.cfg.get("recent_sources", []), path)
        # Immediately refresh all source dropdowns to include recent sources in this session
        for cb in self.source_combos:
            cb["values"] = [CLEAR_LABEL] + self.cfg.get("recent_sources", [])

    def _on_source_selected(self, idx: int):
        val = self.source_combos[idx].get().strip()
        if val == CLEAR_LABEL:
            self._set_source_path(idx, "")
        else:
            self._set_source_path(idx, val)

    # (Removed: _schedule_redraw and redraw_arrows methods)

    def update_target_highlight(self):
        GREEN = "#AAF792"   # light green (default for main/sources)
        RED   = "#F79595"   # light red  (active when alternative is chosen)
        GRAY  = "#EEEEEE"   # neutral/inactive

        alt_active = bool(self.use_alt_var.get() and self.alt_library_var.get().strip())

        # Main library: green when alt is NOT active, otherwise neutral gray   
        if hasattr(self, "library_wrap"):
            self.library_wrap.configure(bg=GRAY if alt_active else GREEN)

        # Alternative target: red when active, otherwise neutral gray        
        if hasattr(self, "alt_wrap"):
            self.alt_wrap.configure(bg=RED if alt_active else GRAY)

        # Sources: green when main is active; red when alternative is active
        for w in getattr(self, "source_wraps", []):
            try:
                w.configure(bg=RED if alt_active else GREEN)
            except Exception:
                pass

    def update_alt_controls(self):
        state = "normal" if self.use_alt_var.get() else "disabled"
        self.alt_combo.configure(state=state)
        for _ in self.children.values():    
            pass
      
    def update_arrows(self):
        # Now only updates controls + visual highlight (no arrow canvas)
        self.update_alt_controls()
        self.update_target_highlight()            
        
    def on_delete_toggle(self, idx: int):
        """Called when the delete-after checkbox is toggled for a source slot."""
        # If user UNchecks the box: do nothing and return (no dialog!)
        if not self.source_delete_vars[idx].get():
            return

        # Global "don't show again"?
        if bool(self.cfg.get("delete_warn_suppressed_global", False)):
            return  # silently accept ON for any source

        # Not globally suppressed -> ask once, then remember globally
        ok, dont_again = DeleteConfirmDialog.ask(self, f"Source {idx+1}")
        if not ok:
            # user canceled → revert checkbox to OFF and exit
            self.source_delete_vars[idx].set(False)
            return
        if dont_again:
            self.cfg["delete_warn_suppressed_global"] = True
            save_cfg(self.cfg)      
    def inline_begin(self):
        """Start the inline progress bar immediately in pulsing mode."""
        try:
            self.inline_bar.stop()
            self.inline_bar.configure(mode="indeterminate", maximum=1)
            self.inline_bar.start(60)  # pulse every ~60 ms
            self._inline_pulsing = True
            self.inline_eta.configure(text="ETA: —")
            try:
                self.inline_pct.configure(text="Scanning…")
            except Exception:
                pass
        except Exception:
            pass
    def inline_set_total(self, total:int):
        try:
            # We now know the total -> switch to DETERMINATE immediately
            self.inline_bar.stop()
            self.inline_bar.configure(mode="determinate", maximum=max(1, int(total)))
            self.inline_bar["value"] = 0
            self._inline_pulsing = False
            self.inline_eta.configure(text="ETA: —")
            try:
                self.inline_pct.configure(text="0%")  
            except Exception:
                pass
            self.update_idletasks()
        except Exception:
            pass

    def inline_update_progress(self, current:int, start_t:float, total: int|None):
        try:
            # Force determinate mode on every tick so the bar fills left->right
            self.inline_bar.stop()
            self.inline_bar.configure(mode="determinate")            
            # On first real tick, switch from pulsing to determinate
            if self._inline_pulsing:
                self.inline_bar.stop()
                self.inline_bar.configure(mode="determinate")
                self._inline_pulsing = False            
            if total:
                self.inline_bar.configure(maximum=max(1, int(total)))
            maxv = int(self.inline_bar["maximum"]) or 1
            self.inline_bar["value"] = min(int(current), maxv)
            # Update percentage label on the left
            try:
                pct = int(100 * min(int(current), maxv) / maxv)
                self.inline_pct.configure(text=f"{pct}%")
            except Exception:
                pass
            elapsed = time.time() - start_t
            if current > 0:
                rate = elapsed / current
                remaining = max(0, int((maxv - int(current)) * rate))
                self.inline_eta.configure(text=f"ETA: {remaining}s")
            self.update_idletasks()
        except Exception:
            pass

    def inline_done(self):
        try:
            self.inline_bar.stop()
            self.inline_bar.configure(mode="determinate")            
            maxv = int(self.inline_bar["maximum"]) or 1
            self.inline_bar["value"] = maxv
            self.inline_eta.configure(text="ETA: 0s")
            try:
                self.inline_pct.configure(text="100%")
            except Exception:
                pass
            self.inline_bar.configure(mode="determinate")            
        except Exception:
            pass

    # ---------- run ----------
    def start_merge(self):
        # Prevent re-entry while a run is active
        if getattr(self, "running", False):
            return

        # Ensure no combobox dropdown stays open (which could steal focus)
        try:
            to_close = []
            try:
                to_close.append(self.library_combo)
            except Exception:
                pass
            try:
                to_close.append(self.alt_combo)
            except Exception:
                pass
            for cb in getattr(self, "source_combos", []):
                to_close.append(cb)
            for cb in to_close:
                try:
                    cb.event_generate("<Escape>")
                except Exception:
                    pass
            self.focus_force()
        except Exception:
            pass

        target = self.alt_library_var.get().strip() if (self.use_alt_var.get() and self.alt_library_var.get().strip()) else self.library_var.get().strip()
        if not target:
            return messagebox.showwarning("Missing target", "Please select a target directory (Main or Alternative).")
        # Build a list of (slot_index, path) so we can report per source in the summary
        selected = [(i + 1, self._normalized_src(v.get())) for i, v in enumerate(self.source_vars)]
        selected = [(i, p) for (i, p) in selected if p]
        sources = [p for (_, p) in selected]
        if not sources:
            return messagebox.showwarning("Missing source", "Please select at least one source folder.")
        if not os.path.exists(SCRIPT_PATH):
            return messagebox.showerror("Missing file", f"kopiere_einzigartige.py not found:\n{SCRIPT_PATH}")
        # Nochmals sicherstellen: kein veralteter Index blockiert das Kopieren
        try:
            self._maybe_reset_index(target)
        except Exception:
            pass

        # Remember per-source delete-after flag (stable by original slot index)
        delete_map = {}
        for i in range(6):
            s = self._normalized_src(self.source_vars[i].get())
            if s:
                delete_map[s] = bool(self.source_delete_vars[i].get())

        self.save_now()

        # Mark as running and disable Start button
        self.running = True
        try:
            self.start_btn.configure(state="disabled")
        except Exception:
            pass

        # --- No Control window during merge ---

        # Start inline progress immediately in pulsing mode
        self.inline_begin()
        self.update_idletasks()

        # Pause watcher during merge to avoid interference
        try:
            if hasattr(self, "library_observer"):
                self.library_observer.stop()
                self.library_observer.join()
        except Exception:
            pass

        # Pre-count in a background thread; when known, switch both bars to determinate
        def _precount():
            try:
                t = sum(self._count_audio_files(s) for s in sources)
            except Exception:
                t = 0
            if t > 0:
                self.after(0, lambda: self.inline_set_total(t))

        threading.Thread(target=_precount, daemon=True).start()

        # Kommando aufbauen – wir rufen das Skript einmal pro Source auf,
        # damit "delete-after" wirklich nur für diese Source gilt.
        def worker():
            overall = {"copied":0, "dups":0, "errors":0, "processed":0}
            log_lines = []
            leftovers = {}
            self.stop_requested = False  # Track if stopped
            for src in sources:
                cmd = [sys.executable, "-u", SCRIPT_PATH, "--ziel", target, src]
                if delete_map.get(src):
                    cmd.insert(3, "--delete-after")
                cmd += ["--progress-every", "1"]

                # Bestand vorher (für "übrig" Berechnung)
                before = self._count_audio_files(src)

                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,  # line-buffered so progress arrives immediately
                    env={**os.environ, "PYTHONUNBUFFERED": "1"}
                )
                total = None
                start_t = time.time()
                for line in proc.stdout:
                    log_lines.append(line)
                    if "Gesamt zu prüfen:" in line:
                        try:
                            total = int(line.strip().split(":")[1].split()[0])
                            self.after(0, lambda t=total: self.inline_set_total(t))
                        except Exception:
                            pass
                    if line.startswith("…bearbeitet:"):
                        # …bearbeitet: i  (kopiert: c, Duplikate: d, klein/Meta: m)
                        try:
                            parts = line.replace("…bearbeitet:", "").strip().split()
                            i = int(parts[0])
                            self.after(0, lambda c=i, st=start_t, tt=total: self.inline_update_progress(c, st, tt))
                        except Exception:
                            pass
                rc = proc.wait()
                # Am Ende Summary Werte herausziehen (letzte 6 Zeilen)
                # Wir lesen das Log-Widget zurück, pragmatisch:
                tail = "\n".join(log_lines[-40:])
                def _grab(tag):
                    for ln in reversed(tail.splitlines()):
                        if ln.startswith(tag):
                            try:
                                return int(ln.split()[-1])
                            except: return 0
                    return 0
                copied = _grab("Kopiert:")
                dups   = _grab("Duplikate (Inhalt):")
                errs   = _grab("Fehler:")
                procd  = _grab("Verarbeitet:")

                overall["copied"] += copied
                overall["dups"]   += dups
                overall["errors"] += errs
                overall["processed"] += procd

                # Bestand nachher
                after = self._count_audio_files(src)
                leftovers[src] = after

            self.after(0, self.inline_done)
            # Re-enable Start button when done
            self.after(0, lambda: (setattr(self, "running", False), self.start_btn.configure(state="normal")))

            # Abschluss-Summary: write into Control window instead of popup
            summary = (f"Copied: {overall['copied']}\n"
                       f"Duplicates (content): {overall['dups']}\n"
                       f"Errors: {overall['errors']}\n"
                       f"Total processed: {overall['processed']}\n\n"
                       "Remaining files per source (music files only):\n" +
                       "\n".join(
                           f"• Source {i}: {os.path.basename(p) or p} — {leftovers.get(p, 0)}"
                           for (i, p) in selected
                       ))
            # Show popup only if not stopped
            if not self.stop_requested:
                self.after(0, lambda: messagebox.showinfo("Finished", summary))

            # Restart watcher after merge completes
            def restart_watcher():
                try:
                    self.library_observer = Observer()
                    self.library_watcher = LibraryWatcher(self.library_var.get())
                    self.library_observer.schedule(self.library_watcher, path=self.library_var.get(), recursive=True)
                    self.library_observer.start()
                except Exception as e:
                    print("Watcher restart failed:", e)
            self.after(1000, restart_watcher)

        threading.Thread(target=worker, daemon=True).start()

    def _count_audio_files(self, folder):
        exts = {".mp3",".flac",".alac",".m4a",".aac",".ogg",".opus",".wav",".aif",".aiff",".wma"}
        skip_dirs = {".Spotlight-V100", ".Trashes", ".fseventsd"}
        n=0
        for r, _, files in os.walk(folder):
            for f in files:
                if f.startswith('.'):  # skip hidden files like .DS_Store
                    continue
                ext = os.path.splitext(f)[1].lower()
                if ext in exts:
                    n += 1
        return n

    def _index_path_for(self, target: str) -> str:
        """Pfad zur Index-Datei im Zielordner zurückgeben."""
        return os.path.join(target, ".musik_index.db")

    def _maybe_reset_index(self, target: str):
        """If the target is empty but an index file exists, offer to reset."""
        try:
            if not target:
                return
            idx = self._index_path_for(target)
            # Target has no music files, but an index file exists → ask
            if os.path.exists(idx) and self._count_audio_files(target) == 0:
                if messagebox.askyesno(
                    "Reset index",
                    "The target folder contains no music files, but an index file exists.\n"
                    "Do you want to reset the index (.musik_index.db) so files can be added again?"
                ):
                    try:
                        os.remove(idx)
                    except Exception:
                        pass
        except Exception:
            pass

    def save_now(self):
        # Persist main settings, but do NOT persist sources or their recent list        
        self.cfg["library"] = self.library_var.get().strip()
        self.cfg["use_alt"] = bool(self.use_alt_var.get())
        self.cfg["alt_library"] = self.alt_library_var.get().strip()
        # Do not persist sources / recent_sources so the app starts clean
        self.cfg["sources"] = ["" for _ in range(6)]
        self.cfg["recent_sources"] = []
        # Keep recent_targets for convenience       
        self.cfg["recent_targets"] = add_recent(self.cfg.get("recent_targets", []), self.library_var.get().strip())
        save_cfg(self.cfg)

    def close_library_finder(self):
        """Close the Finder window we opened (by id). If no id is stored, try closing a window that shows the current Library path."""
        try:
            # Fast path: close by stored id
            if getattr(self, "_finder_win_id", None):
                script = (
                    'tell application "Finder"\n'
                    '    try\n'
                    '        if exists (window id {wid}) then close (window id {wid})\n'
                    '    end try\n'
                    'end tell\n'
                ).format(wid=int(self._finder_win_id))
                subprocess.run(["osascript", "-e", script], check=False)
                self._finder_win_id = None
                return

            # Fallback: close a front window that matches current Library path (best effort)
            path = (self.library_combo.get() or "").strip()
            if not path:
                return
            p = os.path.abspath(path)
            p_slash = p if p.endswith('/') else p + '/'
            p_slash_esc = p_slash.replace('"', '\\"')
            script2 = (
                'tell application "Finder"\n'
                '    if (count of windows) > 0 then\n'
                '        try\n'
                '            set fp to POSIX path of (target of front window as alias)\n'
                '            if fp is "{p_slash}" then close front window\n'
                '        end try\n'
                '    end if\n'
                'end tell\n'
            ).format(p_slash=p_slash_esc)
            subprocess.run(["osascript", "-e", script2], check=False)
        except Exception:
            pass

    def on_close(self):
        self.save_now()
        # Close Finder windows showing the current library/alt paths
        try:
            self.close_library_finder()
            time.sleep(0.1)
        except Exception:
            pass
        try:
            if hasattr(self, "library_observer"):
                self.library_observer.stop()
                self.library_observer.join()
        except Exception:
            pass
        self.destroy()

    def reset_delete_warnings(self):
        """Reset all 'Don't show again' flags for delete-after confirmation."""
        self.cfg["delete_warn_suppressed"] = [False]*6
        self.cfg["delete_warn_suppressed_global"] = False
        save_cfg(self.cfg)
        messagebox.showinfo("Warnings", "Delete-after warnings will be shown again.")

class StatusWindow:
    def __init__(self, parent, total_hint=None):
        self.win = tk.Toplevel(parent)
        self.win.title("Control")
        self.win.geometry("720x420")
        self.text = tk.Text(self.win, height=14)
        self.text.pack(fill="both", expand=True, padx=10, pady=(10,4))
        barf = ttk.Frame(self.win); barf.pack(fill="x", padx=10, pady=(0,10))
        # start as indeterminate so animation is visible immediately; we switch to determinate in set_total()
        self.bar = ttk.Progressbar(barf, mode="indeterminate", maximum=1)
        self.bar.pack(fill="x")
        self.eta_lbl = ttk.Label(barf, text="ETA: —")
        self.eta_lbl.pack(anchor="e")
        self.total = total_hint or 0
        self.start_time = time.time()

    def show(self):
        # Make it a transient child of the main window
        try:
            parent = self.win.master
            self.win.transient(parent)
        except Exception:
            self.win.transient()

        # Compute position: left-aligned next to the main app window
        self.win.update_idletasks()
        try:
            parent = self.win.master
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            ph = parent.winfo_height()
            ww = self.win.winfo_width()
            wh = self.win.winfo_height()

            # place to the LEFT of the app, aligned to the top edge
            x = px - ww - 8
            y = py

            # Clamp to screen bounds (avoid negative X)
            if x < 0:
                x = 8
            screen_h = parent.winfo_screenheight()
            if y + wh > screen_h:
                y = max(0, screen_h - wh - 20)

            self.win.geometry(f"+{x}+{y}")
        except Exception:
            pass

        # Show and focus
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()
        # Start indeterminate animation immediately; will switch to determinate on first total/progress
        try:
            self.bar.stop()
            self.bar.configure(mode="indeterminate")
            self.bar.start(60)  # ~60ms tick
            self.win.update_idletasks()
        except Exception:
            pass
    def append(self, line:str):
        self.text.insert("end", line)
        self.text.see("end")

    def set_total(self, total:int):
        # switch to determinate as soon as we know total
        try:
            self.bar.stop()
            self.bar.configure(mode="determinate")
        except Exception:
            pass
        self.total = max(1, total)
        self.bar.configure(maximum=self.total)
        self.bar["value"] = 0
        try:
            self.win.update_idletasks()
        except Exception:
            pass

    def update_progress(self, current:int, start_t:float, total: int|None):
        """Update the progress bar and ETA.
        Ensures the bar is in determinate mode on every tick
        so it fills left→right immediately when totals arrive.
        """
        try:
            # If the script now reports a total, switch our bar to determinate
            if total:
                self.set_total(total)

            # Enforce determinate mode (in case we were still pulsing)
            try:
                self.bar.stop()
                self.bar.configure(mode="determinate")
            except Exception:
                pass

            if self.total:
                # Clamp to maximum and update value
                self.bar["value"] = min(int(current), int(self.total))

                # ETA calculation
                elapsed = time.time() - start_t
                if current > 0:
                    rate = elapsed / float(current)
                    remaining = max(0, int((int(self.total) - int(current)) * rate))
                    self.eta_lbl.configure(text=f"ETA: {remaining}s")
            self.win.update_idletasks()
        except Exception:
            pass

    def get_tail(self, n_lines:int) -> str:
        return self.text.get("end-{}l linestart".format(n_lines), "end")

    def done(self):
        self.bar["value"] = self.total
        self.eta_lbl.configure(text="ETA: 0s")

class DeleteConfirmDialog(tk.Toplevel):
    """
    Modal confirmation dialog used before deleting source files.
    Shows:
      - question text ("Are you sure ...?")
      - a 'Don't show again' checkbox
      - OK / Cancel buttons
    Usage:
        ok, dont_show_again = DeleteConfirmDialog.ask(parent, source_label_text)
    """
    def __init__(self, parent, source_label="this source"):
        super().__init__(parent)
        self.title("Confirm deletion")
        self.resizable(False, False)
        self.ok = False
        self.dont_again_var = tk.BooleanVar(value=False)

        # start hidden to avoid flicker
        self.withdraw()
        self.update_idletasks()

        # Frame
        frm = ttk.Frame(self, padding=12)
        frm.grid(row=0, column=0, sticky="nsew")

        # Message
        msg = ttk.Label(
            frm,
            text=f"Are you sure you want to permanently delete files from {source_label} after transfer?",
            wraplength=420,
            justify="left"
        )
        msg.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0,8))

        # Don't show again
        chk = ttk.Checkbutton(frm, text="Don't show this message again", variable=self.dont_again_var)
        chk.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0,12))

        # Buttons
        btn_ok = ttk.Button(frm, text="OK", command=self._on_ok)
        btn_cancel = ttk.Button(frm, text="Cancel", command=self._on_cancel)
        btn_cancel.grid(row=2, column=0, sticky="e", padx=(0,6))
        btn_ok.grid(row=2, column=1, sticky="w")

        # Modal behavior
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Return>", lambda e: self._on_ok())
        self.bind("<Escape>", lambda e: self._on_cancel())

        # Center on parent
        self.update_idletasks()
        if parent is not None:
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            w  = self.winfo_width()
            h  = self.winfo_height()
            x = px + (pw - w)//2
            y = py + (ph - h)//2
            self.geometry(f"+{x}+{y}")
            # show now without flicker
            self.deiconify()
            self.lift()
            self.focus_force()

    def _on_ok(self):
        self.ok = True
        self.destroy()

    def _on_cancel(self):
        self.ok = False
        self.destroy()

    @classmethod
    def ask(cls, parent, source_label="this source"):
        dlg = cls(parent, source_label)
        parent.wait_window(dlg)
        return dlg.ok, bool(dlg.dont_again_var.get())
if __name__ == "__main__":
    App().mainloop()

