# 1. IMPORTS (todas as bibliotecas necessárias)
import os
import yt_dlp
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Security, status, BackgroundTasks
from fastapi.security import APIKeyHeader
from fastapi.responses import FileResponse
from pydantic import BaseModel

# 2. CARREGAR VARIÁVEIS DE AMBIENTE
load_dotenv()

# 3. CONFIGURAÇÕES INICIAIS
app = FastAPI(title="API de Download TikTok")

API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise ValueError("A variável de ambiente 'API_KEY' não foi configurada!")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FFMPEG_PATH = "ffmpeg"   # O static-ffmpeg coloca o executável no PATH

class DownloadRequest(BaseModel):
    url: str

# 4. FUNÇÃO DE VALIDAÇÃO DA API KEY
async def validar_api_key(api_key: str = Security(api_key_header)):
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chave de API não fornecida. Inclua o cabeçalho 'X-API-Key'.",
            headers={"WWW-Authenticate": "X-API-Key"},
        )
    if api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chave de API inválida. Acesso negado.",
        )
    return api_key

# 5. ENDPOINT PÚBLICO (opcional)
@app.get("/")
async def root():
    return {"mensagem": "Bem-vindo à API de Download do TikTok. Use /docs para a documentação."}

# 6. ENDPOINT PARA DOWNLOAD DE VÍDEO (MP4)
@app.post("/download/video")
async def download_video(request: DownloadRequest, api_key: str = Depends(validar_api_key)):
    url = request.url
    downloads_dir = os.path.join(BASE_DIR, "downloads")
    os.makedirs(downloads_dir, exist_ok=True)

    ydl_opts = {
        'format': 'best',
        'outtmpl': os.path.join(downloads_dir, '%(title)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            if os.path.exists(file_path):
                return FileResponse(
                    path=file_path,
                    filename=os.path.basename(file_path),
                    media_type="video/mp4"
                )
            else:
                raise HTTPException(status_code=404, detail="Arquivo não encontrado após download")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao baixar vídeo: {str(e)}")

# 7. ENDPOINT PARA DOWNLOAD DE ÁUDIO (MP3)
@app.post("/download/audio")
async def download_audio(request: DownloadRequest, api_key: str = Depends(validar_api_key)):
    url = request.url
    downloads_dir = os.path.join(BASE_DIR, "downloads")
    os.makedirs(downloads_dir, exist_ok=True)

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(downloads_dir, '%(title)s.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            base = os.path.splitext(ydl.prepare_filename(info))[0]
            mp3_path = base + ".mp3"
            if os.path.exists(mp3_path):
                return FileResponse(
                    path=mp3_path,
                    filename=os.path.basename(mp3_path),
                    media_type="audio/mpeg"
                )
            else:
                raise HTTPException(status_code=404, detail="Arquivo MP3 não encontrado após processamento")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao baixar áudio: {str(e)}")