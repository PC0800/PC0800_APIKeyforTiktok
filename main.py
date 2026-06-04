# 1. IMPORTS (todas as bibliotecas necessárias)
import time
import os
import yt_dlp
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Security, status, Request
from fastapi.security import APIKeyHeader
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Rate limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Logging
from fastapi_ndjson_logger import RequestResponseLogging

# 2. CARREGAR VARIÁVEIS DE AMBIENTE
load_dotenv()

# 3. CONFIGURAÇÕES INICIAIS
app = FastAPI(title="API de Download TikTok")

# --- Configuração do Rate Limiting ---
limiter = Limiter(key_func=get_remote_address, default_limits=["100/hour"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# --- Configuração do Logging ---
os.makedirs("logs", exist_ok=True)
app.add_middleware(
    RequestResponseLogging,
    log_dir=os.path.join("logs"),  # Diretório onde os logs serão salvos
    max_mbytes=10,                 # Tamanho máximo de cada arquivo de log (em MB)
    backup_count=5                 # Número de arquivos de backup a serem mantidos
)

# --- CORS ---
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://tiktok-downloader-8y2.pages.dev"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise ValueError("A variável de ambiente 'API_KEY' não foi configurada!")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FFMPEG_PATH = "ffmpeg"

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

# 5. ENDPOINTS
@app.get("/")
async def root():
    return {"mensagem": "Bem-vindo à API de Download do TikTok. Use /docs para a documentação."}

@app.post("/download/video")
@limiter.limit("3/minute")
async def download_video(request: DownloadRequest, request_obj: Request, api_key: str = Depends(validar_api_key)):
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

@app.post("/download/audio")
@limiter.limit("3/minute")
async def download_audio(request: DownloadRequest, request_obj: Request, api_key: str = Depends(validar_api_key)):
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

@app.get("/info")
@limiter.limit("10/minute")
async def get_video_info(request: Request, url: str, api_key: str = Depends(validar_api_key)):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            titulo = info.get('title', 'Vídeo TikTok')
            thumbnail_url = None
            if info.get('thumbnails'):
                thumbnail_url = info['thumbnails'][-1]['url']
            return {
                "success": True,
                "title": titulo,
                "thumbnail": thumbnail_url
            }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao obter informações: {str(e)}")

@app.delete("/cleanup")
@limiter.limit("1/minute")
async def cleanup_old_files(request: Request, api_key: str = Depends(validar_api_key), hours: int = 1):
    downloads_dir = os.path.join(BASE_DIR, "downloads")
    if not os.path.exists(downloads_dir):
        return {"message": "Pasta downloads não existe"}
    now = time.time()
    deleted = 0
    for filename in os.listdir(downloads_dir):
        filepath = os.path.join(downloads_dir, filename)
        if os.path.isfile(filepath):
            file_age_hours = (now - os.path.getmtime(filepath)) / 3600
            if file_age_hours > hours:
                os.remove(filepath)
                deleted += 1
    return {"message": f"Limpeza concluída. {deleted} arquivos removidos."}