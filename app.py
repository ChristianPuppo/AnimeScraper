import os
from flask import Flask, render_template, request, jsonify, Response, redirect, url_for, session, send_file, abort
from flask_sqlalchemy import SQLAlchemy
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin, unquote
from collections import defaultdict
from dotenv import load_dotenv
from tmdbv3api import TMDb, TV, Season, Episode
from fuzzywuzzy import fuzz
import json
import uuid
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Abilita CORS per tutte le route

# Configurazione del database
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///playlists.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class SharedPlaylist(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    playlist = db.Column(db.Text, nullable=False)

    def __init__(self, id, name, playlist):
        self.id = id
        self.name = name
        self.playlist = playlist

BASE_URL = "https://www.animesaturn.cx"

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
        video_url = extract_video_url(urljoin(BASE_URL, streaming_link['href']))
        if video_url:
            return video_url
    return None

def extract_video_url(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        iframe = soup.find('iframe')
        if iframe and 'src' in iframe.attrs:
            iframe_src = iframe['src']
            iframe_response = requests.get(iframe_src)
            iframe_response.raise_for_status()
            video_pattern = r'(https?://.*?\.(?:m3u8|mp4))'

            iframe_soup = BeautifulSoup(iframe_response.text, 'html.parser')
            for script in iframe_soup.find_all('script'):
                match = re.search(video_pattern, str(script))
                if match:
                    return match.group(0)

            match = re.search(video_pattern, iframe_response.text)
            if match:
                return match.group(0)

        video_pattern = r'(https?://.*?\.(?:m3u8|mp4))'
        for script in soup.find_all('script'):
            match = re.search(video_pattern, str(script))
            if match:
                return match.group(0)

        match = re.search(video_pattern, response.text)
        if match:
            return match.group(0)

    except requests.RequestException as e:
        print(f"Errore nell'estrazione dell'URL video: {e}")

    return None

def get_series_metadata(title, season_number=1):
    try:
        print(f"DEBUG: Cercando serie su TMDb: {title}")
        search_title = renamed_titles.get(title, title)
        search_title = re.sub(r'\s*(\(ITA\)|\(SUB ITA\)|\(TV\)|\(OAV\)|\(OVA\))\s*', '', search_title).strip()
        
        # Rimuovi il numero della stagione dal titolo di ricerca
        original_season_number = season_number
        season_match = re.search(r'\s+(\d+)$', search_title)
        if season_match:
            season_number = int(season_match.group(1))
            search_title = re.sub(r'\s+\d+$', '', search_title)
        
        print(f"DEBUG: Titolo di ricerca modificato: {search_title}, Stagione: {season_number}")
        
        search = tv.search(search_title)
        if not search:
            print(f"DEBUG: Nessun risultato trovato per '{search_title}', provo con la prima metà del titolo")
            search = tv.search(search_title[:len(search_title)//2])
        
        if search:
            best_match = max(search, key=lambda x: fuzz.ratio(x.name.lower(), search_title.lower()))
            print(f"DEBUG: Serie trovata su TMDb: {best_match.name} (ID: {best_match.id})")
            details = tv.details(best_match.id)
            
            # Cerca la stagione specificata
            target_season = next((s for s in details.seasons if s.season_number == season_number), None)
            if not target_season:
                print(f"DEBUG: Stagione {season_number} non trovata, uso la prima stagione disponibile")
                target_season = details.seasons[0]
            
            print(f"DEBUG: Recuperando dettagli per la stagione {target_season.season_number}")
            season_details = Season().details(best_match.id, target_season.season_number)
            episodes = []
            for ep in season_details.episodes:
                episode_name = ep.name if ep.name else f"Episodio {ep.episode_number}"
                episodes.append({
                    'season_number': target_season.season_number,
                    'episode_number': ep.episode_number,
                    'name': episode_name,
                    'title': f"S{target_season.season_number}E{ep.episode_number} - {episode_name}"
                })
            print(f"DEBUG: Totale episodi trovati: {len(episodes)}")
            return {
                'id': best_match.id,
                'title': f"{details.name} - Stagione {season_number}",
                'original_title': details.original_name,
                'overview': details.overview,
                'first_air_date': details.first_air_date,
                'genres': [genre['name'] for genre in details.genres],
                'poster_path': f"https://image.tmdb.org/t/p/w500{details.poster_path}" if details.poster_path else None,
                'episodes': episodes,
                'season_number': target_season.season_number
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
    video_url = get_streaming_url(episode_url)
    if video_url:
        print(f"URL video estratto: {video_url}")
        return jsonify({"video_url": video_url})
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
        
        # Estrai il numero della stagione dal titolo, se presente
        season_match = re.search(r'\s+(\d+)$', series_title)
        season_number = int(season_match.group(1)) if season_match else 1
        
        metadata = get_series_metadata(series_title, season_number)
        
        if metadata and 'episodes' in metadata:
            tmdb_episodes = {ep['episode_number']: ep['name'] for ep in metadata['episodes']}
            print(f"DEBUG: Episodi trovati su TMDb per {series_title} (Stagione {metadata['season_number']}): {tmdb_episodes}")
        else:
            tmdb_episodes = {}
            print(f"DEBUG: Nessun episodio trovato su TMDb per {series_title}")
        
        for i, episode in enumerate(series['episodes'], 1):
            episode_number = i
            episode_title = tmdb_episodes.get(episode_number)
            
            if episode_title:
                print(f"DEBUG: Usando titolo TMDb per episodio {episode_number}: {episode_title}")
                m3u_content += f"#EXTINF:-1,S{metadata['season_number']}E{episode_number} - {episode_title} - {series_title}\n"
            else:
                print(f"DEBUG: Usando titolo generico per episodio {episode_number}")
                m3u_content += f"#EXTINF:-1,S{metadata['season_number']}E{episode_number} - Episodio {episode_number} - {series_title}\n"
            
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
        
        new_playlist = SharedPlaylist(id=share_id, name=playlist_name, playlist=json.dumps(playlist))
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
    try:
        data = request.json
        playlist = data.get('playlist')
        playlist_name = data.get('playlist_name')
        share_id = data.get('share_id')

        if not all([playlist, playlist_name, share_id]):
            return jsonify({"error": "Dati mancanti per l'aggiornamento della playlist"}), 400

        shared_playlist = SharedPlaylist.query.get(share_id)
        if not shared_playlist:
            return jsonify({"error": "Playlist non trovata"}), 404

        shared_playlist.name = playlist_name
        shared_playlist.playlist = json.dumps(playlist)
        db.session.commit()

        share_url = url_for('download_shared_playlist', share_id=share_id, _external=True)
        return jsonify({'share_url': share_url, 'share_id': share_id})
    except Exception as e:
        print(f"DEBUG: Errore durante l'aggiornamento della playlist condivisa - {str(e)}")
        db.session.rollback()
        return jsonify({"error": "Si è verificato un errore durante l'aggiornamento della playlist"}), 500

@app.route('/get_series_metadata', methods=['POST'])
def get_series_metadata_route():
    data = request.json
    title = data.get('title')
    if not title:
        return jsonify({"error": "Titolo mancante"}), 400
    
    metadata = get_series_metadata(title)
    if metadata:
        return jsonify(metadata)
    else:
        return jsonify({"error": "Metadata non trovati"}), 404

@app.route('/stream/<path:video_url>')
def stream_video(video_url):
    try:
        # Decodifica l'URL del video
        decoded_url = unquote(video_url)
        # Effettua una richiesta al server video
        response = requests.get(decoded_url, stream=True)
        return Response(response.iter_content(chunk_size=1024),
                        content_type=response.headers['Content-Type'])
    except Exception as e:
        print(f"Errore nello streaming del video: {str(e)}")
        abort(500)

def init_db():
    with app.app_context():
        db.create_all()
        print("Database tables created.")

# Aggiungi questa riga dopo la definizione di init_db()
init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)