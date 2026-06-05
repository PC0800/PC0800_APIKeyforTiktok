# 1. IMPORTS
import time
import os
import logging
import secrets
import yt_dlp
import requests                     # Expandir links curtos
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Security, status, Request
from fastapi.security import APIKeyHeader
from fastapi.responses import FileResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.middleware.cors import CORSMiddleware

# 2. CARREGAR VARIÁVEIS DE AMBIENTE
load_dotenv()

# 3. CONFIGURAÇÕES INICIAIS
app = FastAPI(title="API de Download TikTok")

# Rate Limiting
limiter = Limiter(key_func=get_remote_address, default_limits=["100/hour"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Logging
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "app.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("api")

# Middleware de log
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000
    client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"
    logger.info(f'Method={request.method} Path={request.url.path} Status={response.status_code} Duration={process_time:.2f}ms IP={client_ip}')
    return response

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Verificação da chave de API ---
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    logger.error("A variável de ambiente 'API_KEY' não foi configurada!")
    raise ValueError("A variável de ambiente 'API_KEY' não foi configurada!")
else:
    logger.info(f"API_KEY carregada: {API_KEY[:3]}... (tamanho: {len(API_KEY)})")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class DownloadRequest(BaseModel):
    url: str
    video_quality: str = None
    audio_quality: str = None

# 🔥 FUNÇÃO PARA EXPANDIR LINKS ENCURTADOS
def expand_tiktok_url(url: str) -> str:
    """Segue redirecionamentos e retorna a URL final do vídeo."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        response.raise_for_status()
        expanded = response.url
        logger.info(f"URL expandida: {expanded}")
        return expanded
    except Exception as e:
        logger.warning(f"Falha ao expandir URL {url}: {e}")
        return url  # fallback

# 🔥 FUNÇÃO DE LIMPEZA
def clean_tiktok_url(url: str) -> str:
    """Remove parâmetros de rastreamento e garante https."""
    if not url:
        return url
    if '?' in url:
        url = url.split('?')[0]
    if not url.startswith('http'):
        url = 'https://' + url
    return url

# 🔥 FUNÇÃO PARA CONVERTER URL DE FOTO EM URL DE VÍDEO (áudio)
def fix_photo_url(url: str) -> str:
    """Se for uma URL de álbum de fotos, substitui '/photo/' por '/video/' para extrair áudio."""
    if '/photo/' in url:
        fixed = url.replace('/photo/', '/video/')
        logger.info(f"URL de foto convertida para vídeo: {fixed}")
        return fixed
    return url

# --------------------------------------------------------------
# VALIDAÇÃO DA API KEY
# --------------------------------------------------------------
async def validar_api_key(api_key: str = Security(api_key_header)):
    logger.info(f"Validando API Key recebida: '{api_key[:5] if api_key else 'None'}...' (tamanho: {len(api_key) if api_key else 0})")
    if api_key is None:
        logger.warning("Nenhuma chave fornecida")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chave de API não fornecida. Inclua o cabeçalho 'X-API-Key'.",
            headers={"WWW-Authenticate": "X-API-Key"},
        )
    if not secrets.compare_digest(api_key, API_KEY):
        logger.warning(f"Chave inválida fornecida (início: {api_key[:5]})")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chave de API inválida. Acesso negado.",
        )
    logger.info("Chave válida, acesso permitido")
    return api_key

# --------------------------------------------------------------
# ENDPOINTS
# --------------------------------------------------------------
@app.get("/")
async def root():
    return {"mensagem": "Bem-vindo à API de Download do TikTok. Use /docs para a documentação."}

# --------------------------------------------------------------
# DOWNLOAD DE VÍDEO (com expansão e correção para posts de foto)
# --------------------------------------------------------------
@app.post("/download/video")
@limiter.limit("5/minute")
async def download_video(request: Request, download_req: DownloadRequest, api_key: str = Depends(validar_api_key)):
    # LIMPEZA + EXPANSÃO + CORREÇÃO DE FOTO
    url = clean_tiktok_url(download_req.url.strip())
    url = expand_tiktok_url(url)
    url = fix_photo_url(url)   # 🔥 Converte /photo/ em /video/ para extrair áudio

    qualidade = download_req.video_quality
    height_map = {"1080p": 1080}
    max_height = height_map.get(qualidade)
    format_spec = f"best[height<={max_height}]" if max_height else "best"

    downloads_dir = os.path.join(BASE_DIR, "downloads")
    os.makedirs(downloads_dir, exist_ok=True)

    ydl_opts = {
        'format': format_spec,
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
        logger.error(f"Erro no download do vídeo: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Erro ao baixar vídeo: {str(e)}")

# --------------------------------------------------------------
# DOWNLOAD DE ÁUDIO (com expansão e correção para posts de foto)
# --------------------------------------------------------------
@app.post("/download/audio")
@limiter.limit("5/minute")
async def download_audio(request: Request, download_req: DownloadRequest, api_key: str = Depends(validar_api_key)):
    url = clean_tiktok_url(download_req.url.strip())
    url = expand_tiktok_url(url)
    url = fix_photo_url(url)   # 🔥 Converte /photo/ em /video/ para extrair áudio

    qualidade = download_req.audio_quality
    quality_map = {
        "64kbps": "64",
        "128kbps": "128",
        "256kbps": "256",
        "320kbps": "320",
    }
    bitrate = quality_map.get(qualidade, "192")

    downloads_dir = os.path.join(BASE_DIR, "downloads")
    os.makedirs(downloads_dir, exist_ok=True)

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(downloads_dir, '%(title)s.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': bitrate,
        }],
        'quiet': True,
        'no_warnings': True,
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
                raise HTTPException(status_code=404, detail="Arquivo MP3 não encontrado")
    except Exception as e:
        logger.error(f"Erro no download do áudio: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Erro ao baixar áudio: {str(e)}")

# --------------------------------------------------------------
# INFORMAÇÕES DO VÍDEO (com expansão e correção para posts de foto)
# --------------------------------------------------------------
@app.get("/info")
@limiter.limit("10/minute")
async def get_video_info(request: Request, url: str, api_key: str = Depends(validar_api_key)):
    url = clean_tiktok_url(url)
    url = expand_tiktok_url(url)
    url = fix_photo_url(url)   # 🔥 Converte /photo/ em /video/ para extrair informações

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

# --------------------------------------------------------------
# LIMPEZA
# --------------------------------------------------------------
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