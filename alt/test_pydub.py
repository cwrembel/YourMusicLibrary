from pydub.audio_segment import AudioSegment  # wichtig: Untermodul direkt!

print("AudioSegment import klappt:", AudioSegment is not None)

# 1 Sekunde Stille erzeugen (ohne Datei lesen/ohne Playback):
seg = AudioSegment.silent(duration=1000)
print("Dummy-Sound erzeugt:", seg.duration_seconds, "Sekunde")
