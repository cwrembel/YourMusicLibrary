#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, argparse, shutil, json
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from typing import Set
from suche_musik import finde_musikdateien
from hashing import hash_robust as berechne_audio_hash


INDEX_NAME = ".musik_index.db"  # einfache JSON-Datei mit Hashes (Set)
MAP_NAME = ".hash_map.json"  # Pfad->Hash Zuordnung für Watchdog
CACHE_NAME = ".hash_cache.json"  # pro-Source Cache (RELATIVER Pfad -> {hash,size,mtime})


AUDIO_EXTS = {
    ".mp3", ".flac", ".alac", ".m4a", ".m4b", ".aac", ".m4p",
    ".ogg", ".oga", ".opus", ".spx",
    ".wav", ".aif", ".aiff", ".aifc", ".caf",
    ".wma", ".ape", ".wv", ".mka", ".mkv", ".mp4", ".weba",
    ".dsd", ".dff", ".dsf",
    ".mid", ".midi",
    ".amr", ".3gp", ".3g2",
    ".ac3", ".dts",
    ".au", ".snd", ".pcm",
    ".mpc", ".tta", ".tak"
}

# --- Windows helper: hide cache file in Explorer ---

def _hide_file_windows(path: str) -> None:
    """Hide a file in Windows Explorer (no-op on other OS)."""
    try:
        if not sys.platform.startswith("win"):
            return
        import ctypes
        from ctypes import wintypes

        FILE_ATTRIBUTE_HIDDEN = 0x02

        GetFileAttributesW = ctypes.windll.kernel32.GetFileAttributesW
        GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
        GetFileAttributesW.restype = wintypes.DWORD

        SetFileAttributesW = ctypes.windll.kernel32.SetFileAttributesW
        SetFileAttributesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
        SetFileAttributesW.restype = wintypes.BOOL

        attrs = GetFileAttributesW(path)
        # INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
        if attrs == 0xFFFFFFFF:
            return

        # Preserve existing attributes, just add HIDDEN
        new_attrs = attrs | FILE_ATTRIBUTE_HIDDEN
        SetFileAttributesW(path, new_attrs)
    except Exception:
        pass

def index_path(target: str) -> str:
    return os.path.join(target, INDEX_NAME)

def load_index(path: str) -> Set[str]:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
    except Exception:
        pass
    return set()

def save_index(path: str, hashes: Set[str]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sorted(list(hashes)), f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        # Index-Schreiben soll nie den Lauf killen
        pass


# --- Hash-Map-Helpers ---
def map_path(target: str) -> str:
    return os.path.join(target, MAP_NAME)

def load_map(path: str) -> dict:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}

def save_map(path: str, mapping: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass

def update_hash_map(target_dir: str, file_path: str, h: str) -> None:
    try:
        mp = map_path(target_dir)
        m = load_map(mp)
        # watchdog liefert in der Regel absolute Pfade; wir speichern ebenfalls absolut
        p_abs = os.path.abspath(file_path)
        m[p_abs] = h
        save_map(mp, m)
    except Exception:
        pass

# --- Source Cache Helpers (per Quelle) ---
def source_cache_path(src_dir: str) -> str:
    return os.path.join(src_dir, CACHE_NAME)

def load_source_cache(path: str) -> dict:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}

def save_source_cache(path: str, cache: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass

def _stat_tuple(fp: str):
    try:
        st = os.stat(fp)
        # mtime nur grob in Sekunden; reicht für Change-Detection
        return (int(st.st_size), int(st.st_mtime))
    except Exception:
        return None

def unique_target_path(target_dir: str, filename: str) -> str:
    base, ext = os.path.splitext(filename)
    out = os.path.join(target_dir, filename)
    i = 1
    while os.path.exists(out):
        out = os.path.join(target_dir, f"{base}({i}){ext}")
        i += 1
    return out

def main():
    ap = argparse.ArgumentParser(description="Kopiert einzigartige Musikdateien (Inhalts-Hash) in ein Ziel.")
    ap.add_argument("quelle", help="Quellordner")
    ap.add_argument("--ziel", required=True, help="Zielordner")
    ap.add_argument("--delete-after", action="store_true",
                    help="Nach erfolgreichem Kopieren Originaldatei in der Quelle löschen")
    ap.add_argument("--progress-every", type=int, default=25,
                    help="Nach wie vielen Dateien einen Fortschritts-Tick drucken (GUI liest '…bearbeitet: N')")
    args = ap.parse_args()

    src = os.path.abspath(args.quelle)
    dst = os.path.abspath(args.ziel)
    os.makedirs(dst, exist_ok=True)

    # Per-Source Cache laden
    scache_path = source_cache_path(src)
    scache = load_source_cache(scache_path)

    # Cache-Key: relativer Pfad innerhalb der Quelle (macht Cache robust gegen wechselnde Mountpoints,
    # z.B. wenn ein USB-Stick aus- und wieder eingesteckt wird).
    def _cache_key(fp_abs: str) -> str:
        try:
            rel = os.path.relpath(fp_abs, src)
        except Exception:
            rel = fp_abs
        # Normalisieren, damit Windows/Unix-Trenner konsistent sind
        return rel.replace("\\", "/")

    # Aktuelle Datei-Liste (relative Cache-Keys) für spätere Cache-Bereinigung
    current_keys = set()

    # Dateien sammeln
    files = finde_musikdateien(src)
    total = len(files)

    # GUI erwartet diese Zeile exakt:
    print(f"Gesamt zu prüfen: {total}", flush=True)

    # Index laden
    idx_path = index_path(dst)
    seen = load_index(idx_path)

    copied = 0
    dups = 0
    errs = 0
    processed = 0

    # Session-Set, damit Duplikate innerhalb derselben Quelle sofort erkannt werden
    session_seen: Set[str] = set()

    for fp in files:
        processed += 1

        fp_abs = os.path.abspath(fp)
        key = _cache_key(fp_abs)
        current_keys.add(key)
        st = _stat_tuple(fp)

        # Backward-compat: alte Caches hatten absolute Pfade als Keys.
        cached = scache.get(key)
        if cached is None:
            old = scache.get(fp_abs)
            if isinstance(old, dict):
                cached = old
                # migriere direkt auf das neue Key-Format
                scache[key] = old
                try:
                    scache.pop(fp_abs, None)
                except Exception:
                    pass

        h = None
        if cached and st and (cached.get("size") == st[0]) and (int(cached.get("mtime", 0)) == st[1]):
            # Cache-Hit: Hash nicht erneut berechnen
            h = cached.get("hash")
        else:
            # Hash neu berechnen und Cache aktualisieren (falls erfolgreich)
            h = berechne_audio_hash(fp)
            if h and st:
                scache[key] = {"hash": h, "size": st[0], "mtime": st[1]}

        if not h:
            errs += 1
            if args.progress_every > 0 and (processed % args.progress_every == 0):
                print(f"…bearbeitet: {processed}", flush=True)
            continue

        if (h in seen) or (h in session_seen):
            dups += 1
            if args.progress_every > 0 and (processed % args.progress_every == 0):
                print(f"…bearbeitet: {processed}", flush=True)
            continue

        # neuer Inhalt → kopieren
        try:
            target_path = unique_target_path(dst, os.path.basename(fp))
            shutil.copy2(fp, target_path)
            copied += 1
            session_seen.add(h)
            seen.add(h)

            update_hash_map(dst, target_path, h)

            if args.delete_after:
                try:
                    os.remove(fp)
                    # keep source cache in sync (file no longer exists in source)
                    scache.pop(key, None)
                    # backward-compat cleanup (falls noch vorhanden)
                    scache.pop(fp_abs, None)
                except Exception:
                    errs += 1
        except Exception:
            errs += 1

        if args.progress_every > 0 and (processed % args.progress_every == 0):
            print(f"…bearbeitet: {processed}", flush=True)

    # finaler Tick (falls total kein Vielfaches von progress_every ist)
    if args.progress_every > 0 and (processed % args.progress_every != 0):
        print(f"…bearbeitet: {processed}", flush=True)

    # Index speichern
    save_index(idx_path, seen)

    # Cache-Bereinigung: Einträge entfernen, die es in der Quelle nicht mehr gibt
    # (wir vergleichen jetzt relative Keys)
    try:
        stale = [k for k in list(scache.keys()) if k not in current_keys]
        if stale:
            for k in stale:
                scache.pop(k, None)
        save_source_cache(scache_path, scache)
        _hide_file_windows(scache_path)
    except Exception:
        pass

    # GUI liest diese Summary-Schlüsselwörter:
    print(f"Kopiert: {copied}", flush=True)
    print(f"Duplikate (Inhalt): {dups}", flush=True)
    print(f"Fehler: {errs}", flush=True)
    print(f"Verarbeitet: {processed}", flush=True)

if __name__ == "__main__":
    main()