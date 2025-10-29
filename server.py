from flask import Flask, jsonify, request, send_file, Response, stream_with_context
import yt_dlp as youtube_dl
import requests
import urllib.parse
import random
import time
from urllib.parse import quote
import re
import logging
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Middleware CORS manual
@app.after_request
def after_request(response):
    # Ensure single-value CORS headers (avoid duplicate values like '*, *')
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
    return response

# Configuração avançada do yt-dlp com headers aleatórios e opções para diferentes estratégias
def get_ydl_opts():
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
    ]
    
    return {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': False,
        'extract_flat': False,
        'ignoreerrors': True,
        'no_check_certificate': True,
        'geo_bypass': True,
        'geo_bypass_country': 'US',
        'http_headers': {
            'User-Agent': random.choice(user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
                'player_skip': ['configs', 'webpage'],
            }
        },
    }

def get_ydl_fast_opts():
    opts = get_ydl_opts()
    opts['extract_flat'] = True
    return opts


def safe_extract_info(ydl, url, retry_count=3):
    """Extrai informações com retry em caso de erro e detecção de bloqueio por bot."""
    for attempt in range(retry_count):
        try:
            # Delay aleatório entre tentativas
            if attempt > 0:
                time.sleep(random.uniform(1, 3))
                # rotate user-agent header if available
                if 'http_headers' in ydl.params:
                    ua_list = ydl.params['http_headers'].get('User-Agent')
            info = ydl.extract_info(url, download=False)
            return info
        except youtube_dl.utils.DownloadError as e:
            if "bot" in str(e).lower() or "sign in" in str(e).lower():
                logger.warning(f"Detectado bloqueio de bot (tentativa {attempt + 1})")
                if attempt == retry_count - 1:
                    raise e
                continue
            else:
                raise e
        except Exception as e:
            if attempt == retry_count - 1:
                raise e
            continue
    return None


def alternative_search(query):
    """Método alternativo de busca quando o principal falha"""
    try:
        # Método 1: Usar invidious ou instância alternativa
        return search_via_invidious(query)
    except Exception:
        # Método 2: Busca simulada como fallback
        return [{
            'id': 'dQw4w9WgXcQ',
            'title': f'{query} (busca alternativa)',
            'duration': '3:33',
            'isVideo': True
        }]


def search_via_invidious(query):
    """Busca usando instância Invidious alternativa"""
    try:
        instances = [
            'https://inv.riverside.rocks',
            'https://invidious.snopyta.org',
            'https://yewtu.be',
            'https://invidious.kanicloud.com'
        ]
        for instance in instances:
            try:
                search_url = f"{instance}/api/v1/search?q={quote(query)}&type=video"
                response = requests.get(search_url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    videos = []
                    for item in data[:10]:
                        videos.append({
                            'id': item.get('videoId'),
                            'title': item.get('title', 'Sem título'),
                            'duration': format_duration(item.get('lengthSeconds', 0)),
                            'isVideo': True
                        })
                    return videos
            except Exception:
                continue
        return []
    except Exception:
        return []


def fast_search(query):
    """Busca rápida no YouTube com proteção anti-bot"""
    try:
        ydl_opts = get_ydl_fast_opts()
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            # Verifica se é URL direta
            video_id = extract_video_id(query)
            playlist_id = extract_playlist_id(query)
            if video_id:
                url = f"https://www.youtube.com/watch?v={video_id}"
                info = safe_extract_info(ydl, url)
                if not info:
                    return []
                return [{
                    'id': info.get('id'),
                    'title': info.get('title', 'Sem título'),
                    'duration': format_duration(info.get('duration', 0)),
                    'isVideo': True,
                    'url': url
                }]
            elif playlist_id:
                url = f"https://www.youtube.com/playlist?list={playlist_id}"
                info = safe_extract_info(ydl, url)
                if not info:
                    return []
                videos = []
                for entry in info.get('entries', [])[:20]:
                    if entry:
                        videos.append({
                            'id': entry.get('id'),
                            'title': entry.get('title', 'Sem título'),
                            'duration': format_duration(entry.get('duration', 0)),
                            'isVideo': True,
                            'url': entry.get('url')
                        })
                return videos
            else:
                # Busca por texto usando método alternativo
                return alternative_search(query)
    except Exception as e:
        logger.error(f"Erro na busca rápida: {e}")
        return alternative_search(query)


def get_audio_url(video_id):
    """Obtém URL de áudio com múltiplas estratégias"""
    strategies = [
        get_audio_direct,
        get_audio_via_invidious,
        get_audio_fallback
    ]
    for strategy in strategies:
        try:
            result = strategy(video_id)
            if result and result.get('success'):
                return result
        except Exception as e:
            logger.warning(f"Estratégia {strategy.__name__} falhou: {e}")
            continue
    return {'success': False, 'error': 'Todas as estratégias falharam'}


def get_audio_direct(video_id):
    """Estratégia direta com yt-dlp"""
    try:
        ydl_opts = get_ydl_opts()
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            url = f"https://www.youtube.com/watch?v={video_id}"
            info = safe_extract_info(ydl, url)
            if not info:
                return {'success': False}
            return {
                'success': True,
                'audioUrl': info.get('url'),
                'title': info.get('title', 'Sem título'),
                'duration': info.get('duration', 0),
                'thumbnail': info.get('thumbnail', ''),
                'channel': info.get('uploader', '')
            }
    except Exception as e:
        logger.error(f"Erro no método direto: {e}")
        return {'success': False}


def get_audio_via_invidious(video_id):
    """Estratégia usando Invidious para obter áudio"""
    try:
        instances = [
            'https://inv.riverside.rocks',
            'https://invidious.snopyta.org',
            'https://yewtu.be'
        ]
        for instance in instances:
            try:
                api_url = f"{instance}/api/v1/videos/{video_id}"
                response = requests.get(api_url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    best_audio = None
                    for fmt in data.get('adaptiveFormats', []):
                        if (fmt.get('type', '').startswith('audio/') and fmt.get('url')):
                            if not best_audio or fmt.get('bitrate', 0) > best_audio.get('bitrate', 0):
                                best_audio = fmt
                    if best_audio:
                        return {
                            'success': True,
                            'audioUrl': best_audio['url'],
                            'title': data.get('title', 'Sem título'),
                            'duration': data.get('lengthSeconds', 0),
                            'thumbnail': data.get('videoThumbnails', [{}])[0].get('url', ''),
                            'channel': data.get('author', '')
                        }
            except Exception:
                continue
        return {'success': False}
    except Exception as e:
        logger.error(f"Erro no método Invidious: {e}")
        return {'success': False}


def get_audio_fallback(video_id):
    """Estratégia de fallback usando métodos públicos"""
    try:
        fallback_url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts = get_ydl_opts()
        ydl_opts['extractor_args'] = {
            'youtube': {
                'player_client': ['android', 'ios', 'web'],
                'player_skip': ['configs', 'webpage', 'js'],
            }
        }
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(fallback_url, download=False)
            return {
                'success': True,
                'audioUrl': info.get('url'),
                'title': info.get('title', 'Sem título'),
                'duration': info.get('duration', 0),
                'thumbnail': info.get('thumbnail', ''),
                'channel': info.get('uploader', '')
            }
    except Exception as e:
        logger.error(f"Erro no método fallback: {e}")
        return {'success': False}

def extract_video_id(url_or_query):
    """Extrai o ID do vídeo de forma rápida"""
    patterns = [
        r'(?:v=|youtu\.be/|embed/)([^&?/\n]{11})',
        r'^[a-zA-Z0-9_-]{11}$'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url_or_query)
        if match:
            return match.group(1)
    return None

def extract_playlist_id(url):
    """Extrai o ID da playlist"""
    match = re.search(r'[&?]list=([^&]+)', url)
    return match.group(1) if match else None

def fast_search(query):
    """Busca rápida no YouTube"""
    try:
        ydl_opts = get_ydl_fast_opts()
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            # Verifica se é URL direta
            video_id = extract_video_id(query)
            playlist_id = extract_playlist_id(query)
            
            if video_id:
                url = f"https://www.youtube.com/watch?v={video_id}"
                info = ydl.extract_info(url, download=False)
                return [{
                    'id': info.get('id'),
                    'title': info.get('title', 'Sem título'),
                    'duration': format_duration(info.get('duration', 0)),
                    'isVideo': True,
                    'url': url
                }]
            
            elif playlist_id:
                url = f"https://www.youtube.com/playlist?list={playlist_id}"
                info = ydl.extract_info(url, download=False)
                videos = []
                for entry in info.get('entries', [])[:50]:  # Limita a 50 músicas
                    if entry:
                        videos.append({
                            'id': entry.get('id'),
                            'title': entry.get('title', 'Sem título'),
                            'duration': format_duration(entry.get('duration', 0)),
                            'isVideo': True,
                            'url': entry.get('url')
                        })
                return videos
            
            else:
                # Busca por texto - método mais rápido
                search_query = f"ytsearch10:{query}"
                info = ydl.extract_info(search_query, download=False)
                videos = []
                for entry in info.get('entries', [])[:10]:
                    if entry:
                        videos.append({
                            'id': entry.get('id'),
                            'title': entry.get('title', 'Sem título'),
                            'duration': format_duration(entry.get('duration', 0)),
                            'isVideo': True,
                            'url': entry.get('url')
                        })
                return videos
                
    except Exception as e:
        logger.error(f"Erro na busca rápida: {e}")
        return []

def get_audio_url(video_id):
    """Obtém URL de áudio de forma rápida"""
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        ydl_opts = get_ydl_opts()
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            # Try to obtain a usable media URL. Some info dicts contain 'url' directly,
            # otherwise pick a best audio format from 'formats'.
            audio_url = info.get('url')
            if not audio_url and 'formats' in info:
                # prefer audio-only formats
                formats = info.get('formats', [])
                # pick the first audio-only or the best available
                chosen = None
                for f in formats:
                    if f.get('acodec') and f.get('vcodec') in (None, 'none'):
                        chosen = f
                        break
                if not chosen and formats:
                    chosen = formats[-1]
                if chosen:
                    audio_url = chosen.get('url')

            if not audio_url:
                raise RuntimeError('No audio URL found')

            # Return a proxied URL so the browser fetches from our server (fixes CORS).
            proxied = f"{request.scheme}://{request.host}/proxy?url={urllib.parse.quote_plus(audio_url)}"

            return {
                'success': True,
                'audioUrl': proxied,
                'title': info.get('title', 'Sem título'),
                'duration': info.get('duration', 0),
                'thumbnail': info.get('thumbnail', ''),
                'channel': info.get('uploader', '')
            }
                
    except Exception as e:
        logger.error(f"Erro ao obter áudio: {e}")
        return {'success': False, 'error': str(e)}

def format_duration(seconds):
    """Formata duração em segundos para MM:SS"""
    if not seconds:
        return "0:00"
    
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    
    if minutes > 60:
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}:{mins:02d}:{secs:02d}"
    
    return f"{minutes}:{secs:02d}"

@app.route('/search', methods=['GET', 'OPTIONS'])
def search():
    """Endpoint de busca rápida"""
    if request.method == 'OPTIONS':
        return '', 200
        
    query = request.args.get('q', '').strip()
    
    if not query:
        return jsonify([])
    
    try:
        logger.info(f"Buscando: {query}")
        results = fast_search(query)
        logger.info(f"Encontrados {len(results)} resultados")
        return jsonify(results)
    except Exception as e:
        logger.error(f"Erro no endpoint /search: {e}")
        return jsonify({'error': 'Falha na busca'}), 500

@app.route('/stream/<video_id>', methods=['GET', 'OPTIONS'])
def stream(video_id):
    """Endpoint rápido para obter stream de áudio"""
    if request.method == 'OPTIONS':
        return '', 200
        
    try:
        logger.info(f"Obtendo stream para: {video_id}")
        stream_info = get_audio_url(video_id)
        
        if stream_info['success']:
            return jsonify(stream_info)
        else:
            return jsonify({'error': stream_info.get('error', 'Stream não encontrado')}), 404
            
    except Exception as e:
        logger.error(f"Erro no endpoint /stream: {e}")
        return jsonify({'error': 'Falha ao obter stream'}), 500

@app.route('/play', methods=['GET'])
def play_direct():
    """Endpoint direto para tocar música"""
    query = request.args.get('q', '').strip()
    
    if not query:
        return jsonify({'error': 'Parâmetro q é obrigatório'}), 400
    
    try:
        # Busca o vídeo
        results = fast_search(query)
        if not results:
            return jsonify({'error': 'Nenhum resultado encontrado'}), 404
        
        # Pega o primeiro resultado
        video = results[0]
        
        # Obtém o stream
        stream_info = get_audio_url(video['id'])
        
        if stream_info['success']:
            response_data = {
                'video': video,
                'stream': stream_info
            }
            return jsonify(response_data)
        else:
            return jsonify({'error': 'Falha ao obter áudio'}), 500
            
    except Exception as e:
        logger.error(f"Erro no play direto: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """Endpoint de saúde"""
    return jsonify({
        'status': 'online', 
        'service': 'YT Proxy Python Fast',
        'timestamp': logging.getLoggerClass().root.handlers[0].baseFilename
    })

@app.route('/')
def index():
    """Página inicial"""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>YT Player Fast</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: #0a0a0a; color: white; }
            .endpoint { background: #1a1a1a; padding: 10px; margin: 5px 0; border-left: 3px solid #ff0000; }
        </style>
    </head>
    <body>
        <h1>🎵 YT Player Fast Server</h1>
        <p>Servidor otimizado para reprodução rápida</p>
        
        <div class="endpoint"><strong>GET /search?q=query</strong> - Buscar vídeos</div>
        <div class="endpoint"><strong>GET /stream/video_id</strong> - Obter áudio</div>
        <div class="endpoint"><strong>GET /play?q=query</strong> - Buscar e tocar direto</div>
        <div class="endpoint"><strong>GET /health</strong> - Status do servidor</div>
        
        <p><a href="/player" style="color: #ff0000;">➡️ Ir para o Player</a></p>
    </body>
    </html>
    '''

@app.route('/player')
def player_page():
    """Página do player"""
    # Serve the bundled index.html as the player (player.html may not exist).
    return send_file('index.html')


@app.route('/proxy')
def proxy():
    """Proxy generic to fetch remote media/manifests and return them with CORS headers.

    If the proxied resource is an M3U8 manifest, rewrite any media/segment URLs to point
    back to this proxy so the browser doesn't request googlevideo directly (avoids CORS).
    """
    target = request.args.get('url', '')
    if not target:
        return jsonify({'error': 'url param required'}), 400

    # Only allow http(s)
    if not target.startswith('http://') and not target.startswith('https://'):
        return jsonify({'error': 'invalid url'}), 400

    try:
        # Forward select headers (User-Agent helps some endpoints)
        headers = {'User-Agent': request.headers.get('User-Agent', 'yt-proxy/1.0')}
        r = requests.get(target, headers=headers, stream=True, timeout=15)
    except Exception as e:
        logger.error(f"Proxy fetch error for {target}: {e}")
        return jsonify({'error': 'failed to fetch target'}), 502

    # Determine content type
    content_type = r.headers.get('Content-Type', '')

    # If it's an HLS manifest (m3u8), rewrite URLs inside
    if 'application/vnd.apple.mpegurl' in content_type or target.endswith('.m3u8') or 'vnd.apple.mpegurl' in content_type or target.lower().endswith('.m3u8'):
        try:
            text = r.text
            lines = text.splitlines()
            out_lines = []
            base = target.rsplit('/', 1)[0]
            for line in lines:
                if not line or line.startswith('#'):
                    out_lines.append(line)
                    continue

                # If line is a relative path, make absolute
                if not line.startswith('http://') and not line.startswith('https://'):
                    abs_url = urllib.parse.urljoin(base + '/', line)
                else:
                    abs_url = line

                # Replace with proxied URL
                prox = f"/proxy?url={urllib.parse.quote_plus(abs_url)}"
                out_lines.append(prox)

            body = '\n'.join(out_lines)
            resp = Response(body, content_type='application/vnd.apple.mpegurl')
            # after_request will set the proper CORS header; don't add here to avoid duplicates
            return resp
        except Exception as e:
            logger.error(f"Error processing m3u8 from {target}: {e}")
            return jsonify({'error': 'failed to process manifest'}), 500

    # For other resources (segments, mp4, etc.) stream bytes back
    def generate():
        try:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        finally:
            r.close()

    resp = Response(stream_with_context(generate()), content_type=content_type)
    # Mirror length if available
    if r.headers.get('Content-Length'):
        resp.headers['Content-Length'] = r.headers.get('Content-Length')
    # after_request will set Access-Control-Allow-Origin
    return resp

if __name__ == '__main__':
    print("🚀 Servidor YT Proxy Python FAST iniciando...")
    print("⚡ Otimizado para velocidade máxima")
    print("📡 Endpoints disponíveis:")
    print("   GET /search?q=query")
    print("   GET /stream/video_id") 
    print("   GET /play?q=query (BUSCA E TOCA DIRETO)")
    print("   GET /health")
    print("   GET /player (PLAYER WEB)")
    print("🔧 Servidor rodando em http://0.0.0.0:3000")
    
    app.run(host='0.0.0.0', port=3000, debug=False, threaded=True)