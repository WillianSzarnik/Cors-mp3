from flask import Flask, jsonify, request, send_file, Response, stream_with_context
import yt_dlp as youtube_dl
import requests
import urllib.parse
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

# Configuração otimizada do yt-dlp
ydl_fast_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'extract_flat': True,  # Mais rápido - não extrai todos os formatos
    'noplaylist': False,
}

ydl_audio_opts = {
    'format': 'bestaudio[ext=m4a]/bestaudio',
    'quiet': True,
    'no_warnings': True,
}

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
        with youtube_dl.YoutubeDL(ydl_fast_opts) as ydl:
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
        
        with youtube_dl.YoutubeDL(ydl_audio_opts) as ydl:
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