# kopiere_einzigartige.py
import os
import argparse
import shutil
import sqlite3
from typing import Dict, List, Optional

from suche_musik import finde_musikdateien
from hashing import hash_robust

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import threading

DB_NAME = ".musik_index.db"

# ---------- Pfad-Helfer ----------
def resolve_path(p: str) -> str:
    """Löst ~, $HOME, Umgebungsvariablen und relative Pfade sauber auf."""
    return os.path.abspath(os.path.expanduser(os.path.expandvars(p)))

def ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)

# ---------- Index (SQLite) ----------
def open_db(index_path: str) -> sqlite3.Connection:
    newly_created = not os.path.exists(index_path)
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    con = sqlite3.connect(index_path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS files (
            hash TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            size INTEGER,
            mtime REAL
        )
    """)
    # leicht performante Einstellungen
    con.execute("PRAGMA journal_mode = WAL;")
    con.execute("PRAGMA synchronous = NORMAL;")
    # Info für den Benutzer
    status = "neu angelegt" if newly_created else "wiederverwendet"
    print(f"Index: {index_path} ({status})")
    return con

def db_has_hash(con: sqlite3.Connection, h: str) -> bool:
    cur = con.execute("SELECT 1 FROM files WHERE hash=? LIMIT 1", (h,))
    return cur.fetchone() is not None

def db_insert(con: sqlite3.Connection, h: str, path: str) -> None:
    try:
        st = os.stat(path)
        con.execute(
            "INSERT OR IGNORE INTO files(hash, path, size, mtime) VALUES (?, ?, ?, ?)",
            (h, path, st.st_size, st.st_mtime)
        )
    except Exception:
        con.execute(
            "INSERT OR IGNORE INTO files(hash, path, size, mtime) VALUES (?, ?, NULL, NULL)",
            (h, path)
        )
    con.commit()

# ---------- Dateinamen ----------
def sanitize_filename(name: str) -> str:
    # minimal sauber: keine Slashes/Null-Bytes
    return name.replace("/", "_").replace("\\", "_").replace("\0", "").strip()

def uniquify_path(dest_dir: str, basename: str) -> str:
    base, ext = os.path.splitext(basename)
    candidate = os.path.join(dest_dir, basename)
    n = 1
    while os.path.exists(candidate):
        candidate = os.path.join(dest_dir, f"{base}({n}){ext}")
        n += 1
    return candidate

# ---------- Hash-Helfer ----------
def hash_single_file(p: str) -> Optional[str]:
    try:
        return hash_robust(p)
    except Exception:
        return None

# ---------- Index-Aktualisieren ----------
class IndexDeletionHandler(FileSystemEventHandler):
    def __init__(self, index_path):
        super().__init__()
        self.index_path = index_path

    def on_deleted(self, event):
        if not event.is_directory:
            self.remove_from_index(event.src_path)

    def remove_from_index(self, filepath):
        import sqlite3
        conn = sqlite3.connect(self.index_path)
        c = conn.cursor()
        try:
            c.execute("DELETE FROM files WHERE path = ?", (filepath,))
            conn.commit()
            print(f"Index aktualisiert: Eintrag entfernt -> {filepath}")
        except sqlite3.Error as e:
            print("Index-Fehler beim Entfernen:", e)
        finally:
            conn.close()

# ---------- Kernlogik ----------
def copy_unique(files: List[str], dest_dir: str, index_path: str, dry_run: bool = False,
                delete_after: bool = False, progress_every: int = 50) -> Dict[str, int]:
    ensure_dir(dest_dir)
    con = open_db(index_path)

    seen_hashes_run: Dict[str, str] = {}

    processed = 0
    copied = 0
    skipped_dupes = 0       # Inhalt schon bekannt (Index oder in diesem Lauf)
    skipped_small = 0       # Dateien ohne sinnvollen Hash (zu klein/defekt)
    name_collisions = 0     # gleicher Name im Ziel, aber anderer Inhalt
    errors = 0
    every = max(1, int(progress_every or 50))

    for i, src in enumerate(files, 1):
        processed = i
        try:
            h = hash_single_file(src)
            if h is None:
                skipped_small += 1
                continue

            # 1) Inhalt schon vorhanden? (Index oder in diesem Lauf)
            if db_has_hash(con, h) or h in seen_hashes_run:
                skipped_dupes += 1
                continue

            # 2) Inhalt ist neu -> Dateiname prüfen
            bn = sanitize_filename(os.path.basename(src))
            dst = os.path.join(dest_dir, bn)

            if os.path.exists(dst):
                # Nur diese eine existierende Zieldatei vergleichen
                h_dst = hash_single_file(dst)
                if h_dst == h:
                    # gleicher Inhalt bereits unter gleichem Namen im Ziel
                    skipped_dupes += 1
                    continue
                else:
                    # anderer Inhalt, gleicher Name -> eindeutigen Namen vergeben
                    dst = uniquify_path(dest_dir, bn)
                    name_collisions += 1

            if not dry_run:
                shutil.copy2(src, dst)
                db_insert(con, h, dst)

            seen_hashes_run[h] = src
            copied += 1

        except KeyboardInterrupt:
            print("\nAbbruch durch Benutzer.")
            break
        except Exception as e:
            print(f"⚠️ Fehler bei {src}: {e}")
            errors += 1

        if i % every == 0:
            # Fortschrittsmeldung für GUI und CLI
            print(f"…bearbeitet: {i} (kopiert: {copied}, Duplikate: {skipped_dupes}, klein/Meta: {skipped_small})", flush=True)
            

    con.close()
    return {
        "processed": processed,
        "copied": copied,
        "skipped_dupes": skipped_dupes,
        "skipped_small": skipped_small,
        "name_collisions": name_collisions,
        "errors": errors,
    }

# ---------- CLI ----------
def main():
    parser = argparse.ArgumentParser(
        description="Kopiert nur einzigartige Musikdateien per Audio-Hash in einen Zielordner – ohne Vollscan des Ziels."
    )
    parser.add_argument("quellen", nargs="+", help="Ein oder mehrere Quellordner/Laufwerke.")
    parser.add_argument("--ziel", required=True, help="Zielordner für die einzigartigen Dateien.")
    parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen, was passieren würde (nichts kopieren).")
    parser.add_argument("--index-path", help="Pfad zur Index-DB (.db). Standard: <ZIEL>/.musik_index.db")
    parser.add_argument("--progress-every", type=int, default=1,
                        help="Wie oft eine Fortschrittszeile ausgegeben wird (alle N Dateien).")
    args = parser.parse_args()

    # Pfade robust auflösen
    ziel = resolve_path(args.ziel)
    quellen = [resolve_path(q) for q in args.quellen]
    index_path = resolve_path(args.index_path) if args.index_path else os.path.join(ziel, DB_NAME)

    # Quellen einsammeln
    alle_dateien: List[str] = []
    for q in quellen:
        if not os.path.isdir(q):
            print(f"⚠️ Übersprungen (kein Ordner): {q}")
            continue
        found = finde_musikdateien(q)
        print(f"Quelle: {q} → {len(found)} Musikdatei(en)")
        alle_dateien.extend(found)

    print(f"Gesamt zu prüfen: {len(alle_dateien)} Datei(en)")

        # --- Index-Watcher starten (löscht Index-Einträge sofort, wenn du in der Library Dateien löscht) ---
    index_path = os.path.join(ziel, DB_NAME) if not args.index_path else resolve_path(args.index_path)
    handler = IndexDeletionHandler(index_path)
    observer = Observer()
    observer.schedule(handler, ziel, recursive=True)
    observer.start()
    print(f"Watcher aktiv: überwacht {ziel}")

    try:
        stats = copy_unique(alle_dateien, ziel, index_path=index_path,
                            dry_run=args.dry_run, progress_every=args.progress_every)
    finally:
        # Watcher sauber stoppen (auch bei Fehlern/Abbruch)
        observer.stop()
        observer.join()


    print("\n— Zusammenfassung —")
    print(f"Verarbeitet:            {stats['processed']}")
    print(f"Kopiert:                {stats['copied']}")
    print(f"Duplikate (Inhalt):     {stats['skipped_dupes']} (übersprungen)")
    print(f"Mini/Meta:              {stats['skipped_small']} (übersprungen)")
    print(f"Namenskollisionen:      {stats['name_collisions']} (anderer Inhalt)")
    print(f"Fehler:                 {stats['errors']}")
    print(f"Zielordner:             {ziel}")
    print(f"Index-Datei:            {index_path}")

if __name__ == "__main__":
    main()
