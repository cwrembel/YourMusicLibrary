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
