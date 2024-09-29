from flask import Flask, render_template, request, jsonify, Response, redirect, url_for, session, send_file
from flask_sqlalchemy import SQLAlchemy
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin
import os
from dotenv import load_dotenv
from tmdbv3api import TMDb, TV, Season, Episode
from fuzzywuzzy import fuzz
import json
import uuid
import zipfile
import tempfile
import threading
import time
import logging
import aiohttp
import asyncio

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///playlists.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith("postgres://"):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class SharedPlaylist(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    playlist = db.Column(db.Text, nullable=False)

    def __init__(self, id, name, playlist):
        self.id = id
        self.name = name
        self.playlist = json.dumps(playlist)

BASE_URL = "https://www.animesaturn.mx"

# Carica le variabili d'ambiente dal file .env
load_dotenv()

# Configurazione TMDb
tmdb = TMDb()
tmdb.api_key = os.getenv('TMDB_API_KEY')
tmdb.language = 'it,en'  # Modifica questa riga
tv = TV()
season = Season()

# Dizionario per memorizzare i titoli rinominati
renamed_titles = {}

app.secret_key = os.getenv('SECRET_KEY', 'una_chiave_segreta_predefinita')

download_tasks = {}

async def get_total_size(episodes):
    async with aiohttp.ClientSession() as session:
        tasks = []
        for episode in episodes:
            streaming_url = get_streaming_url(episode['url'])
            if streaming_url:
                video_url = extract_video_url(streaming_url)
                if video_url:
                    tasks.append(get_file_size(session, video_url))
        sizes = await asyncio.gather(*tasks)
        return sum(sizes)

async def get_file_size(session, url):
    async with session.head(url) as response:
        return int(response.headers.get('Content-Length', 0))

def download_series_task(task_id, anime_url, title):
    logger.info(f"Iniziando la preparazione del download per la serie: {title}")
    episodes = get_episodes(anime_url)
    total_episodes = len(episodes)
    
    update_task_status(task_id, 0, total_episodes, 0, total_episodes, title=title)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        for i, episode in enumerate(episodes):
            try:
                logger.info(f"Preparazione episodio {i+1}/{total_episodes}")
                streaming_url = get_streaming_url(episode['url'])
                if streaming_url:
                    video_url = extract_video_url(streaming_url)
                    if video_url:
                        episode_info = {
                            'url': video_url,
                            'filename': f'episode_{i+1}.mp4'
                        }
                        with open(os.path.join(temp_dir, f'episode_{i+1}.json'), 'w') as f:
                            json.dump(episode_info, f)
                        
                        update_task_status(task_id, i+1, total_episodes, i+1, total_episodes, title=title)
                        logger.info(f"Episodio {i+1}/{total_episodes} preparato con successo.")
                    else:
                        logger.warning(f"Nessun URL video trovato per l'episodio {i+1}")
                else:
                    logger.warning(f"Nessun URL di streaming trovato per l'episodio {i+1}")
            except Exception as e:
                logger.error(f"Errore nella preparazione dell'episodio {i+1}: {str(e)}")
        
        zip_file = os.path.join(temp_dir, f'{title}.zip')
        create_zip(temp_dir, zip_file)
        
        permanent_zip_file = os.path.join('/tmp', f'{title}_{uuid.uuid4()}.zip')
        os.rename(zip_file, permanent_zip_file)
        
        update_task_status(task_id, total_episodes, total_episodes, total_episodes, total_episodes, state='SUCCESS', file_path=permanent_zip_file, title=title)
        logger.info(f"Preparazione completata con successo. File ZIP creato: {permanent_zip_file}")

def update_task_status(task_id, downloaded_size, total_size, current_episode, total_episodes, state='PENDING', file_path=None, error=None, title=None):
    download_tasks[task_id] = {
        'state': state,
        'downloaded_size': downloaded_size,
        'total_size': total_size,
        'current_episode': current_episode,
        'total_episodes': total_episodes,
        'file_path': file_path,
        'error': error,
        'title': title
    }
    logger.info(f"Stato del task {task_id} aggiornato: {download_tasks[task_id]}")

@app.route('/download_series', methods=['POST'])
def download_series():
    data = request.json
    anime_url = data['anime_url']
    title = data['title']
    
    task_id = str(uuid.uuid4())
    download_tasks[task_id] = {
        'state': 'PENDING',
        'downloaded_size': 0,
        'total_size': 0,
        'current_episode': 0,
        'total_episodes': 0,
        'file_path': None,
        'error': None
    }
    
    thread = threading.Thread(target=download_series_task, args=(task_id, anime_url, title))
    thread.start()
    
    return jsonify({'task_id': task_id}), 202

@app.route('/task_status/<task_id>')
def task_status(task_id):
    task = download_tasks.get(task_id, {})
    logger.info(f"Richiesta stato del task {task_id}: {task}")
    return jsonify(task)

@app.route('/download_file/<task_id>')
def download_file(task_id):
    task = download_tasks.get(task_id, {})
    if task.get('state') == 'SUCCESS':
        file_path = task['file_path']
        # Estraiamo il nome del file dal percorso
        file_name = os.path.basename(file_path)
        return send_file(file_path, as_attachment=True, download_name=file_name)
    else:
        return "Il file non è ancora pronto per il download", 404

def download_mp4(mp4_url, output_file, task_id, current_downloaded_size, total_size):
    logger.info(f"Scaricamento file MP4: {mp4_url}")
    response = requests.get(mp4_url, stream=True)
    response.raise_for_status()
    file_size = int(response.headers.get('content-length', 0))
    block_size = 1024 * 1024  # 1 MB
    downloaded_size = 0
    with open(output_file, 'wb') as f:
        for data in response.iter_content(block_size):
            size = f.write(data)
            downloaded_size += size
            current_downloaded_size += size
            progress = (current_downloaded_size / total_size) * 100
            update_task_status(
                task_id,
                current_downloaded_size,
                total_size,
                download_tasks[task_id]['current_episode'],
                download_tasks[task_id]['total_episodes']
            )
            logger.debug(f"Progresso download: {progress:.2f}%")
    logger.info(f"File MP4 scaricato con successo: {output_file}")
    return downloaded_size

@app.route('/rename_title', methods=['POST'])
def rename_title():
    data = request.json
    original_title = data['original_title']
    new_title = data['new_title']
    renamed_titles[original_title] = new_title
    return jsonify({"message": "Titolo rinominato con successo"})

def search_anime(query):
    search_url = urljoin(BASE_URL, f"/animelist?search={query}")
    response = requests.get(search_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    results = soup.find_all('a', class_='badge-archivio')
    return [{"title": result.text.strip(), "url": urljoin(BASE_URL, result['href'])} for result in results]

def get_episodes(anime_url):
    response = requests.get(anime_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    episodes = soup.find_all('a', class_='bottone-ep')
    episode_data = []

    for ep in episodes:
        thumbnail_container = ep.find_previous('div', class_='container shadow rounded bg-dark-as-box mb-3 p-3 w-100 d-flex justify-content-center')
        thumbnail_url = None
        if thumbnail_container:
            thumbnail_img = thumbnail_container.find('img', class_='img-fluid cover-anime rounded')
            if thumbnail_img and 'src' in thumbnail_img.attrs:
                thumbnail_url = thumbnail_img['src']

        episode_title = ep.get('title', '') or ep.text.strip()
        if not episode_title:
            episode_title = f"Episodio {len(episode_data) + 1}"

        episode_data.append({
            "title": episode_title,
            "url": urljoin(BASE_URL, ep['href']),
            "thumbnail": thumbnail_url
        })

    return episode_data

def get_streaming_url(episode_url):
    response = requests.get(episode_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    streaming_link = soup.find('a', href=lambda href: href and 'watch?file=' in href)
    if streaming_link:
        return urljoin(BASE_URL, streaming_link['href'])
    return None

def extract_video_url(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        print(f"Cercando URL video in: {url}")

        iframe = soup.find('iframe')
        if iframe and 'src' in iframe.attrs:
            iframe_src = iframe['src']
            print(f"Trovato iframe con src: {iframe_src}")
            iframe_response = requests.get(iframe_src)
            iframe_response.raise_for_status()
            video_pattern = r'(https?://.*?\.(?:m3u8|mp4))'

            iframe_soup = BeautifulSoup(iframe_response.text, 'html.parser')
            for script in iframe_soup.find_all('script'):
                match = re.search(video_pattern, str(script))
                if match:
                    print(f"URL video trovato: {match.group(0)}")
                    return match.group(0)

            match = re.search(video_pattern, iframe_response.text)
            if match:
                print(f"URL video trovato: {match.group(0)}")
                return match.group(0)

        video_pattern = r'(https?://.*?\.(?:m3u8|mp4))'
        for script in soup.find_all('script'):
            match = re.search(video_pattern, str(script))
            if match:
                print(f"URL video trovato: {match.group(0)}")
                return match.group(0)

        match = re.search(video_pattern, response.text)
        if match:
            print(f"URL video trovato: {match.group(0)}")
            return match.group(0)

        print("Nessun URL video trovato")
    except requests.RequestException as e:
        print(f"Errore nell'estrazione dell'URL video: {e}")

    return None

def get_series_metadata(title):
    try:
        print(f"DEBUG: Cercando serie su TMDb: {title}")
        search_title = renamed_titles.get(title, title)
        search_title = re.sub(r'\s*(\(ITA\)|\(SUB ITA\)|\(TV\)|\(OAV\)|\(OVA\))\s*', '', search_title).strip()
        print(f"DEBUG: Titolo di ricerca modificato: {search_title}")
        
        search = tv.search(search_title)
        if not search:
            print(f"DEBUG: Nessun risultato trovato per '{search_title}', provo con la prima metà del titolo")
            search = tv.search(search_title[:len(search_title)//2])
        
        if search:
            best_match = max(search, key=lambda x: fuzz.ratio(x.name.lower(), search_title.lower()))
            print(f"DEBUG: Serie trovata su TMDb: {best_match.name} (ID: {best_match.id})")
            details = tv.details(best_match.id)
            seasons = details.seasons
            episodes = []
            for s in seasons:
                print(f"DEBUG: Recuperando dettagli per la stagione {s.season_number}")
                season_details = Season().details(best_match.id, s.season_number)
                for ep in season_details.episodes:
                    episode_name = ep.name if ep.name else f"Episodio {ep.episode_number}"
                    print(f"DEBUG: Episodio {ep.episode_number}: {episode_name}")
                    episodes.append({
                        'season_number': s.season_number,
                        'episode_number': ep.episode_number,
                        'name': episode_name
                    })
            print(f"DEBUG: Totale episodi trovati: {len(episodes)}")
            return {
                'id': best_match.id,
                'title': details.name,
                'original_title': details.original_name,
                'overview': details.overview,
                'first_air_date': details.first_air_date,
                'genres': [genre['name'] for genre in details.genres],
                'poster_path': f"https://image.tmdb.org/t/p/w500{details.poster_path}" if details.poster_path else None,
                'episodes': episodes
            }
        
        print(f"DEBUG: Nessuna serie trovata su TMDb per: {search_title}")
    except Exception as e:
        print(f"DEBUG: Errore nel recupero dei metadata da TMDb: {e}")
        import traceback
        traceback.print_exc()
    return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    query = request.form['query']
    results = search_anime(query)
    return jsonify(results)

@app.route('/search_suggestions', methods=['POST'])
def search_suggestions():
    query = request.form['query']
    results = search_anime(query)[:10]  # Limita a 10 suggerimenti
    return jsonify(results)

@app.route('/episodes', methods=['POST'])
def episodes():
    anime_url = request.form['anime_url']
    print(f"Richiesta per gli episodi di: {anime_url}")
    episodes = get_episodes(anime_url)
    print(f"Episodi trovati: {episodes}")
    return jsonify(episodes)

@app.route('/stream', methods=['POST'])
def stream():
    episode_url = request.form['episode_url']
    print(f"Richiesta per lo streaming dell'episodio: {episode_url}")
    streaming_url = get_streaming_url(episode_url)
    if streaming_url:
        video_url = extract_video_url(streaming_url)
        print(f"URL video estratto: {video_url}")
        return jsonify({"video_url": video_url, "streaming_url": streaming_url})
    print("Impossibile trovare il link dello streaming.")
    return jsonify({"error": "Impossibile trovare il link dello streaming."})

@app.route('/save_playlist', methods=['POST'])
def save_playlist():
    playlist = request.json['playlist']
    playlist_name = request.json.get('playlist_name', '').strip()
    
    if not playlist_name:
        return jsonify({"error": "Il nome della playlist non può essere vuoto"}), 400
    
    m3u_content = "#EXTM3U\n"
    
    for series in playlist:
        series_title = series['title']
        print(f"DEBUG: Elaborazione serie: {series_title}")
        metadata = get_series_metadata(series_title)
        
        if metadata and 'episodes' in metadata:
            tmdb_episodes = {ep['episode_number']: ep['name'] for ep in metadata['episodes']}
            print(f"DEBUG: Episodi trovati su TMDb per {series_title}: {tmdb_episodes}")
        else:
            tmdb_episodes = {}
            print(f"DEBUG: Nessun episodio trovato su TMDb per {series_title}")
        
        for i, episode in enumerate(series['episodes'], 1):
            episode_number = i
            episode_title = tmdb_episodes.get(episode_number)
            
            if episode_title:
                print(f"DEBUG: Usando titolo TMDb per episodio {episode_number}: {episode_title}")
                m3u_content += f"#EXTINF:-1,Ep. {episode_number} - {episode_title} - {series_title}\n"
            else:
                print(f"DEBUG: Usando titolo generico per episodio {episode_number}")
                m3u_content += f"#EXTINF:-1,Ep. {episode_number} - Episodio {episode_number} - {series_title}\n"
            
            m3u_content += f"{episode['url']}\n"
        
        m3u_content += "#EXT-X-ENDLIST\n\n"  # Separatore tra serie
    
    print(f"DEBUG: Contenuto M3U generato:\n{m3u_content}")
    
    return Response(
        m3u_content,
        mimetype='text/plain',
        headers={'Content-Disposition': f'attachment; filename="{playlist_name}.m3u"'}
    )

@app.route('/share_playlist', methods=['POST'])
def share_playlist():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Dati JSON mancanti"}), 400
        
        playlist = data.get('playlist')
        if not playlist:
            return jsonify({"error": "Playlist mancante"}), 400
        
        playlist_name = data.get('playlist_name', 'Playlist Anime')
        share_id = str(uuid.uuid4())
        
        print(f"DEBUG: Creazione nuova playlist condivisa - ID: {share_id}, Nome: {playlist_name}")
        
        new_playlist = SharedPlaylist(id=share_id, name=playlist_name, playlist=playlist)
        db.session.add(new_playlist)
        db.session.commit()
        
        share_url = url_for('download_shared_playlist', share_id=share_id, _external=True)
        print(f"DEBUG: Playlist condivisa creata con successo - URL: {share_url}")
        
        return jsonify({'share_url': share_url, 'share_id': share_id})
    except Exception as e:
        print(f"DEBUG: Errore durante la condivisione della playlist - {str(e)}")
        db.session.rollback()
        return jsonify({"error": "Si è verificato un errore durante la condivisione della playlist"}), 500

@app.route('/download_shared_playlist/<share_id>')
def download_shared_playlist(share_id):
    shared_playlist = SharedPlaylist.query.get(share_id)
    if not shared_playlist:
        return "Playlist non trovata", 404
    
    playlist = json.loads(shared_playlist.playlist)
    playlist_name = shared_playlist.name
    
    total_episodes = sum(len(series['episodes']) for series in playlist)
    total_series = len(playlist)
    series_list = [{'title': series['title'], 'episode_count': len(series['episodes'])} for series in playlist]
    
    download_url = url_for('generate_m3u', share_id=share_id, _external=True)
    
    return render_template('shared_playlist.html', 
                           playlist_name=playlist_name,
                           total_episodes=total_episodes,
                           total_series=total_series,
                           series_list=series_list,
                           download_url=download_url)

@app.route('/generate_m3u/<share_id>')
def generate_m3u(share_id):
    shared_playlist = SharedPlaylist.query.get(share_id)
    if not shared_playlist:
        return "Playlist non trovata", 404
    
    playlist = json.loads(shared_playlist.playlist)
    playlist_name = shared_playlist.name
    
    m3u_content = "#EXTM3U\n"
    for series in playlist:
        series_title = series['title']
        metadata = get_series_metadata(series_title)
        
        if metadata and 'episodes' in metadata:
            tmdb_episodes = {ep['episode_number']: ep['name'] for ep in metadata['episodes']}
        else:
            tmdb_episodes = {}
        
        for i, episode in enumerate(series['episodes'], 1):
            episode_number = i
            episode_title = tmdb_episodes.get(episode_number)
            
            if episode_title:
                m3u_content += f"#EXTINF:-1,Ep. {episode_number} - {episode_title} - {series_title}\n"
            else:
                m3u_content += f"#EXTINF:-1,Ep. {episode_number} - Episodio {episode_number} - {series_title}\n"
            
            m3u_content += f"{episode['url']}\n"
        
        m3u_content += "#EXT-X-ENDLIST\n\n"  # Separatore tra serie
    
    return Response(
        m3u_content,
        mimetype='text/plain',
        headers={'Content-Disposition': f'attachment; filename="{playlist_name}.m3u"'}
    )

@app.route('/update_shared_playlist', methods=['POST'])
def update_shared_playlist():
    playlist = request.json['playlist']
    playlist_name = request.json['playlist_name']
    share_id = request.json.get('share_id')

    if not share_id:
        share_id = str(uuid.uuid4())
        new_playlist = SharedPlaylist(id=share_id, name=playlist_name, playlist=playlist)
        db.session.add(new_playlist)
    else:
        shared_playlist = SharedPlaylist.query.get(share_id)
        if shared_playlist:
            shared_playlist.name = playlist_name
            shared_playlist.playlist = json.dumps(playlist)
        else:
            return jsonify({'error': 'Playlist non trovata'}), 404

    db.session.commit()
    share_url = url_for('download_shared_playlist', share_id=share_id, _external=True)
    
    return jsonify({'share_url': share_url, 'share_id': share_id})

def create_zip(source_dir, output_file):
    with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(source_dir):
            for file in files:
                if file.endswith('.json'):
                    zipf.write(os.path.join(root, file), file)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
else:
    # Questo blocco verrà eseguito quando l'app è avviata da Gunicorn
    with app.app_context():
        db.create_all()