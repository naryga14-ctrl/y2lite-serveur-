import os
import re
fromgʻ flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import yt_dlp
import requests

app = Flask(__name__)
# Autorise vos pages Y2Lite et StreamLite à appeler ce serveur depuis n'importe quel domaine
CORS(app)


def sanitize_filename(name):
    """Nettoie le titre d'un fichier pour éviter les caractères interdits."""
    return re.sub(r'[^a-zA-Z0-9_\-\.]', '_', name)[:60]


def build_ydl_format(fmt_or_quality):
    """Choisit le flux audio ou vidéo le plus léger selon le format demandé."""
    mapping = {
        'mp3-64': 'worstaudio/bestaudio[ext=m4a]/bestaudio/best',
        'mp3-128': 'bestaudio[ext=m4a]/bestaudio/best',
        'audio': 'worstaudio/bestaudio[ext=m4a]/bestaudio/best',
        '144p': 'worst[ext=mp4]/best[height<=144][ext=mp4]/best[height<=240]/worst',
        'mp4-240': 'best[height<=240][ext=mp4]/best[height<=240]/worst',
        '240p': 'best[height<=240][ext=mp4]/best[height<=240]/worst',
        'mp4-360': 'best[height<=360][ext=mp4]/best[height<=360]/best',
        '360p': 'best[height<=360][ext=mp4]/best[height<=360]/best',
        'mp4-720': 'best[height<=720][ext=mp4]/best[height<=720]/best',
    }
    return mapping.get(fmt_or_quality, 'best[height<=360][ext=mp4]/best[height<=360]/best')


def extract_media_source(url, fmt_or_quality):
    """Extrait les métadonnées et le flux direct d'une URL via yt-dlp."""
    ydl_opts = {
        'format': build_ydl_format(fmt_or_quality),
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


@app.route('/')
def home():
    """Vérifie que le serveur est en ligne."""
    return jsonify({"status": "ok", "service": "Y2Lite & StreamLite Personal Backend"})


@app.route('/api/info', methods=['GET'])
def get_video_info():
    """Renvoie le titre, la miniature, la taille approximative et le nom de fichier."""
    url = request.args.get('url', '').strip()
    fmt = request.args.get('format', 'mp3-128').strip()

    if not url:
        return jsonify({"error": "URL manquante"}), 400

    try:
        info = extract_media_source(url, fmt)
        title = info.get('title', 'media_y2lite')
        thumbnail = info.get('thumbnail', '')
        filesize = info.get('filesize') or info.get('filesize_approx') or 0
        ext = 'mp3' if fmt.startswith('mp3') or fmt == 'audio' else 'mp4'
        filename = f"{sanitize_filename(title)}.{ext}"

        return jsonify({
            "title": title,
            "thumbnail": thumbnail,
            "filesize": filesize,
            "filename": filename
        })
    except Exception as e:
        return jsonify({"error": f"Extraction impossible : {str(e)}"}), 500


@app.route('/api/download', methods=['GET'])
def download_stream():
    """Diffuse le fichier directement vers l'appareil sans stockage sur le serveur."""
    url = request.args.get('url', '').strip()
    fmt = request.args.get('format', 'mp3-128').strip()
    filename = sanitize_filename(request.args.get('filename', 'media_y2lite.mp4'))

    if not url:
        return jsonify({"error": "URL manquante"}), 400

    try:
        info = extract_media_source(url, fmt)
        direct_url = info.get('url')
        if not direct_url:
            return jsonify({"error": "Flux direct introuvable"}), 404

        http_headers = dict(info.get('http_headers', {}))
        upstream = requests.get(direct_url, headers=http_headers, stream=True, timeout=30)
        upstream.raise_for_status()

        def generate():
            try:
                for chunk in upstream.iter_content(chunk_size=65536):
                    if chunk:
                        yield chunk
            finally:
                upstream.close()

        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': upstream.headers.get('Content-Type', 'application/octet-stream')
        }
        if upstream.headers.get('Content-Length'):
            headers['Content-Length'] = upstream.headers['Content-Length']

        return Response(stream_with_context(generate()), headers=headers)
    except Exception as e:
        return jsonify({"error": f"Erreur de téléchargement : {str(e)}"}), 500


@app.route('/api/stream', methods=['GET'])
def stream_lite_video():
    """Diffuse une version compressée (144p / 240p / 360p / audio) pour StreamLite."""
    url = request.args.get('url', '').strip()
    quality = request.args.get('quality', '144p').strip()

    if not url:
        return jsonify({"error": "URL manquante"}), 400

    try:
        info = extract_media_source(url, quality)
        direct_url = info.get('url')
        if not direct_url:
            return jsonify({"error": "Flux vidéo introuvable"}), 404

        http_headers = dict(info.get('http_headers', {}))
        range_header = request.headers.get('Range')
        if range_header:
            http_headers['Range'] = range_header

        upstream = requests.get(direct_url, headers=http_headers, stream=True, timeout=30)
        upstream.raise_for_status()

        def generate():
            try:
                for chunk in upstream.iter_content(chunk_size=32768):
                    if chunk:
                        yield chunk
            finally:
                upstream.close()

        resp_headers = {
            'Content-Type': upstream.headers.get('Content-Type', 'video/mp4'),
            'Accept-Ranges': 'bytes',
        }
        for header_name in ['Content-Length', 'Content-Range']:
            if upstream.headers.get(header_name):
                resp_headers[header_name] = upstream.headers[header_name]

        return Response(
            stream_with_context(generate()),
            status=upstream.status_code,
            headers=resp_headers
        )
    except Exception as e:
        return jsonify({"error": f"Erreur de lecture : {str(e)}"}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
