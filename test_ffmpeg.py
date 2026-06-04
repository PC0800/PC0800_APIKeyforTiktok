import os
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FFMPEG_PATH = os.path.join(BASE_DIR, "ffmpeg.exe")

# Testa se o arquivo existe
if os.path.exists(FFMPEG_PATH):
    print(f"✅ ffmpeg encontrado em: {FFMPEG_PATH}")
    # Tenta executar para ver versão
    result = subprocess.run([FFMPEG_PATH, "-version"], capture_output=True, text=True)
    print(result.stdout.splitlines()[0])
else:
    print(f"❌ ffmpeg não encontrado no caminho: {FFMPEG_PATH}")