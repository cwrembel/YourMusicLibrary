# YourMusicLibrary

Python desktop app to merge multiple music sources into **one** library while preventing duplicates by **content hashing** (PCM). Includes a fast byte‑hash fallback, a JSON index in the target, and a per‑source hash cache for quick re‑runs. GUI is built with Tkinter.

> This repository contains the code I use as a learning and practice project for my upcoming retraining (Fachinformatiker Anwendungsentwicklung).

---

## ✨ Features
- **Duplicate detection by audio content** (PCM hash via `pydub`/`ffmpeg`) with byte‑hash fallback
- **JSON index** in the target library (`.musik_index.db`) – fast membership checks
- **Per‑source cache** (`.hash_cache.json`) to avoid re‑hashing unchanged files
- **Optional delete‑after‑transfer** with confirmation dialog
- **Inline progress bar & ETA** in the GUI
- **macOS Finder integration** (toggle Finder window for the library; optional positioning)
- Works on **macOS / Windows / Linux** (GUI is Tkinter)

---

## 🧱 Architecture (Modules)
- `app_gui.py` – Tkinter application (paths, sources, progress UI, Finder toggle, calling the worker)
- `kopiere_einzigartige.py` – CLI worker that scans a source, computes hashes, copies unique files, updates indexes/caches
- `hashing.py` – robust hashing (PCM content hash + byte hash fallback)
- `suche_musik.py` – file discovery (recursive, common audio extensions)

**Data files**
- Target index: `<target>/.musik_index.db` *(JSON list of content hashes)*
- Target path→hash map: `<target>/.hash_map.json` *(for fast removals on delete/move)*
- Per‑source cache: `<source>/.hash_cache.json` *(path → {hash,size,mtime})*

> No SQLite is used – the “.db” extension denotes a simple JSON file for human‑readable debugging.

---

## 📦 Requirements
- Python **3.11+** (developed with 3.13)
- `ffmpeg` available for `pydub` (only needed for PCM hashing). If missing, the app falls back to byte hashing.
- Python packages from `requirements.txt`:

```bash
pip install -r requirements.txt
```

### Install ffmpeg (optional but recommended)
- **macOS (Homebrew):** `brew install ffmpeg`
- **Windows:** install from https://ffmpeg.org/ and ensure it’s on PATH
- **Linux (Debian/Ubuntu):** `sudo apt install ffmpeg`

---

## ▶️ Usage
### Start GUI
```bash
python app_gui.py
```
Steps in the app:
1. Choose **Music Library Path** (target)
2. Pick one or more **Source** folders (up to 6). The dropdown keeps the *recent* choices within the session.
3. Optionally enable **Delete files from source after transfer** (with confirmation)
4. Click **Start / Merge**

The GUI shows an inline progress bar and ETA. A summary dialog appears when finished.

### Run worker (CLI) directly
```bash
python kopiere_einzigartige.py <source-folder> --ziel <target-folder> [--delete-after] [--progress-every 1]
```
The command prints:
```
Gesamt zu prüfen: N
…bearbeitet: i
Kopiert: C
Duplikate (Inhalt): D
Fehler: E
Verarbeitet: P
```

---

## 🔁 Index & Cache behavior
- **Index (`.musik_index.db`)** lives in the target and stores content hashes of already imported files → prevents duplicates across sessions.
- **Per‑source cache (`.hash_cache.json`)** stores the last known `{size, mtime, hash}` for each path → unchanged files are **not** re‑hashed on the next run.
- If the target folder is empty but an index exists, the GUI offers to **reset the index** so files can be added again.
- When deleting from the source with *delete‑after‑transfer*, the source cache entry is removed as well.

---

## ⚙️ Configuration & UI Notes
- The app stores runtime settings in `app_config.json` (target recents, UI flags). Source selections are **not persisted** between sessions to keep the UI clean.
- macOS Finder window can be toggled via the **Music Library** button and positioned below the app.

---

## 🚧 Limitations / To‑Do
- PCM hashing requires `ffmpeg`; otherwise byte hashing is used (still safe for identical files, but not format‑agnostic).
- Very large files will take time to decode for PCM hashing; the per‑source cache mitigates repeat runs.
- Packaging as a native app (PyInstaller) is planned as a future step.

---

## 🧑‍💻 Development
Create a virtual environment (optional but recommended):
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\\Scripts\\activate
pip install -r requirements.txt
python app_gui.py
```

Code style and structure aim to be clear and beginner‑friendly (learning project). Pull requests / suggestions are welcome.

---

## 📄 License
MIT (or to be defined)

---

## 📬 Contact
Christian Wrembel · Berlin · cwrembel@icloud.com
