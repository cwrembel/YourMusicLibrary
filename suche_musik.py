# suche_musik.py (angepasst)
import os

def finde_musikdateien(root_pfad, endungen=None):
    if endungen is None:
        endungen = [
            ".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".wma",
            ".aiff", ".aif", ".aifc", ".alac", ".ape", ".opus", ".wv",
            ".mka", ".dsd", ".pcm", ".ra", ".rm", ".mid", ".midi"
        ]

    gefundene_dateien = []

    for aktueller_ordner, ordnernamen, dateinamen in os.walk(root_pfad):
        for datei in dateinamen:
            # 🚨 Filter: ignoriere typische System-/Metadateien
            if (
                datei.startswith("._")         # AppleDouble-Dateien
                or datei.lower() == ".ds_store" # macOS Finder
                or datei.lower() == "thumbs.db" # Windows Explorer
                or datei.lower() == "desktop.ini" # Windows
            ):
                continue  # überspringen

            for ext in endungen:
                if datei.lower().endswith(ext):
                    voller_pfad = os.path.join(aktueller_ordner, datei)
                    gefundene_dateien.append(voller_pfad)
                    break

    return gefundene_dateien
