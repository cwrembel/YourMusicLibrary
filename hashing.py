# hashing.py
import os
import hashlib
from typing import Optional

MIN_FILESIZE_BYTES = 1024        # < 1 KB -> verdächtig -> ignorieren
MIN_AUDIO_DURATION_S = 0.5       # < 0.5 s -> verdächtig -> ignorieren

def _is_too_small(pfad: str) -> bool:
    try:
        return os.path.getsize(pfad) < MIN_FILESIZE_BYTES
    except Exception:
        return True

# --- schneller Byte-Hash (1:1-Kopien) ---
def hash_datei_schnell(pfad: str, blocksize: int = 1024 * 1024) -> Optional[str]:
    if _is_too_small(pfad):
        return None
    sha = hashlib.sha256()
    with open(pfad, "rb") as f:
        while True:
            chunk = f.read(blocksize)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()

# --- Audio-PCM-Hash (robust gegen Container-/Tag-Unterschiede) ---
def hash_audio_pcm(pfad: str,
                   ziel_samplerate: int = 44100,
                   ziel_kanalanzahl: int = 1,
                   ziel_samplebreite: int = 2) -> Optional[str]:
    """
    Dekodiert mit pydub/ffmpeg, normalisiert (SR/Kanäle/Samplebreite)
    und hasht die PCM-Rohdaten (Audio-Inhalt).
    """
    try:
        from pydub import AudioSegment
    except Exception:
        return None

    try:
        seg = AudioSegment.from_file(pfad)

        # extrem kurze "Pseudo-Audios" aussortieren
        if (len(seg) / 1000.0) < MIN_AUDIO_DURATION_S:
            return None

        # Normalisieren der Parameter
        if seg.frame_rate != ziel_samplerate:
            seg = seg.set_frame_rate(ziel_samplerate)
        if seg.channels != ziel_kanalanzahl:
            seg = seg.set_channels(ziel_kanalanzahl)
        if seg.sample_width != ziel_samplebreite:
            seg = seg.set_sample_width(ziel_samplebreite)

        raw = seg.raw_data
        return hashlib.sha256(raw).hexdigest()
    except Exception:
        return None

def hash_robust(pfad: str) -> Optional[str]:
    """
    1) Audio-PCM-Hash (bevorzugt)
    2) Fallback: Datei-Byte-Hash
    """
    # zuerst inhaltsbasiert
    h = hash_audio_pcm(pfad)
    if h is not None:
        return h
    # dann zur Not Byte-Hash
    return hash_datei_schnell(pfad)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Robuste Audio-Hashfunktionen für YourMusicLibrary.
- Primär: PCM-Inhalts-Hash via pydub/ffmpeg (formatunabhängig)
- Fallback: Byte-Hash der Datei (für unbekannte/defekte Formate oder fehlendes ffmpeg)
"""

import os
import sys
import hashlib
from pathlib import Path
from typing import Optional

# --- ffmpeg (optional) automatisch verdrahten, wenn im Bundle mitgeliefert ---

def _wire_ffmpeg_if_bundled() -> None:
    try:
        base = getattr(sys, "_MEIPASS", os.path.dirname(__file__))  # PyInstaller support
        exe = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
        cand = Path(base) / "ffmpeg_bin" / exe
        if cand.exists():
            os.environ["FFMPEG_BINARY"] = str(cand)
    except Exception:
        pass

_wire_ffmpeg_if_bundled()

# --- pydub optional laden ---
try:
    from pydub import AudioSegment  # type: ignore
    HAVE_PYDUB = True
except Exception:
    HAVE_PYDUB = False

# Übliche Audio-Endungen (informativ)
AUDIO_EXTS = {
    ".mp3", ".flac", ".alac", ".m4a", ".aac", ".ogg", ".opus",
    ".wav", ".aif", ".aiff", ".wma", ".ape", ".wv", ".mka", ".dsd",
    ".mid", ".midi", ".ra", ".rm", ".pcm"
}

# --- Byte-Hash (Fallback) ---

def _hash_stream(stream, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha1()
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        h.update(chunk)
    return h.hexdigest()


def hash_file_bytes(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return _hash_stream(f)
    except Exception:
        return None

# --- PCM-Inhalts-Hash (bevorzugt) ---

def hash_pcm(path: str) -> Optional[str]:
    """Hash über dekodierte PCM-Daten + Audio-Parameter (Samplerate/Kanäle/Samplewidth)."""
    if not HAVE_PYDUB:
        return None
    try:
        seg = AudioSegment.from_file(path)
        # Parameter einbeziehen, damit gleiche PCM-Daten mit anderem Header/Container
        # trotzdem konsistent gehasht werden.
        params = f"sr={seg.frame_rate};ch={seg.channels};sw={seg.sample_width}".encode("utf-8")
        h = hashlib.sha1()
        h.update(b"PCM\0")
        h.update(params)
        # Rohdaten streamen (kann groß sein, daher in Chunks)
        raw = seg.raw_data
        # Für sehr große Dateien chunkweise updaten
        mv = memoryview(raw)
        step = 4 * 1024 * 1024
        for i in range(0, len(mv), step):
            h.update(mv[i:i+step])
        return h.hexdigest()
    except Exception:
        return None

# --- Öffentliche API ---

def hash_robust(path: str) -> Optional[str]:
    """Berechnet einen robusten Hash für Audiodateien.
    1) Versuche PCM-Hash via pydub/ffmpeg
    2) Fallback: Byte-Hash der Datei
    Liefert None bei Fehlern.
    """
    # Erst versuchen, den inhaltsbasierten Hash zu bekommen
    h = hash_pcm(path)
    if h:
        return h
    # Fallback auf Byte-Hash (funktioniert für alle Dateien)
    return hash_file_bytes(path)