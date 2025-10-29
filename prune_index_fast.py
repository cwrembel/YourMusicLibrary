import os, sqlite3, sys

def prune_index(index_path: str):
    if not os.path.exists(index_path):
        print("Kein Index gefunden:", index_path)
        return 0, 0

    conn = sqlite3.connect(index_path)
    c = conn.cursor()

    # wir versuchen, gängige Spaltennamen abzudecken
    # erwartete Tabelle: files(hash TEXT PRIMARY KEY, path TEXT, ...)
    # falls deine Tabelle anders heißt, sag Bescheid – dann passe ich es an.
    try:
        c.execute("SELECT hash, path FROM files")
    except sqlite3.Error as e:
        print("Index-Struktur unbekannt oder beschädigt:", e)
        conn.close()
        sys.exit(2)

    rows = c.fetchall()
    total = len(rows)
    missing = []

    for h, p in rows:
        if not p or not os.path.exists(p):
            missing.append((h,))

    if missing:
        c.executemany("DELETE FROM files WHERE hash = ?", missing)
        conn.commit()

    conn.close()
    return total, len(missing)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Benutzung: python prune_index_fast.py <ZIELORDNER>")
        sys.exit(1)

    ziel = sys.argv[1]
    index_path = os.path.join(ziel, ".musik_index.db")
    total, removed = prune_index(index_path)
    print(f"Index geprüft: {total} Einträge, entfernt: {removed}")
