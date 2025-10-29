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
CACHE_NAME = ".hash_cache.json"  # pro-Source Cache (Pfad -> {hash,size,mtime})

AUDIO_EXTS = {
    ".mp3",".flac",".alac",".m4a",".aac",".ogg",".opus",
    ".wav",".aif",".aiff",".wma",".ape",".wv",".mka",".dsd",".mid",".midi",".ra",".rm",".pcm"
}

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

    # Aktuelle Datei-Liste (absolute Pfade) für spätere Cache-Bereinigung
    current_files_abs = set()

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
        current_files_abs.add(fp_abs)
        st = _stat_tuple(fp)
        cached = scache.get(fp_abs)
        h = None
        if cached and st and (cached.get("size") == st[0]) and (int(cached.get("mtime", 0)) == st[1]):
            # Cache-Hit: Hash nicht erneut berechnen
            h = cached.get("hash")
        else:
            # Hash neu berechnen und Cache aktualisieren (falls erfolgreich)
            h = berechne_audio_hash(fp)
            if h and st:
                scache[fp_abs] = {"hash": h, "size": st[0], "mtime": st[1]}

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
    try:
        stale = [p for p in scache.keys() if p not in current_files_abs]
        if stale:
            for p in stale:
                scache.pop(p, None)
        save_source_cache(scache_path, scache)
    except Exception:
        pass

    # GUI liest diese Summary-Schlüsselwörter:
    print(f"Kopiert: {copied}", flush=True)
    print(f"Duplikate (Inhalt): {dups}", flush=True)
    print(f"Fehler: {errs}", flush=True)
    print(f"Verarbeitet: {processed}", flush=True)

if __name__ == "__main__":
    main()