from flask import Flask, render_template, request, jsonify, Response, redirect, url_for, session
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin
from collections import defaultdict
import os
from dotenv import load_dotenv
from tmdbv3api import TMDb, TV, Season, Episode
from fuzzywuzzy import fuzz
import json
import uuid
import datetime

app = Flask(__name__)

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

# Aggiungi questo dizionario per memorizzare le playlist condivise
shared_playlists = {}

app.secret_key = os.getenv('SECRET_KEY', 'una_chiave_segreta_predefinita')

def add_to_history(playlist_name, playlist):
    if 'playlist_history' not in session:
        session['playlist_history'] = []
    
    history_entry = {
        'name': playlist_name,
        'date': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'playlist': [{'title': series['title'], 'episodes': [{'url': ep['url']} for ep in series['episodes']]} for series in playlist]
    }
    
    session['playlist_history'].insert(0, history_entry)
    session['playlist_history'] = session['playlist_history'][:10]  # Mantieni solo le ultime 10 playlist
    session.modified = True

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
    playlist_history = session.get('playlist_history', [])
    # Assicuriamoci che la playlist sia serializzabile
    for item in playlist_history:
        if 'playlist' in item:
            item['playlist'] = json.dumps(item['playlist'])
    return render_template('index.html', playlist_history=playlist_history)

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
    
    add_to_history(playlist_name, playlist)
    
    return Response(
        m3u_content,
        mimetype='text/plain',
        headers={'Content-Disposition': f'attachment; filename="{playlist_name}.m3u"'}
    )

@app.route('/share_playlist', methods=['POST'])
def share_playlist():
    playlist = request.json['playlist']
    playlist_name = request.json.get('playlist_name', 'Playlist Anime')
    share_id = str(uuid.uuid4())
    shared_playlists[share_id] = {'playlist': playlist, 'name': playlist_name}
    share_url = url_for('download_shared_playlist', share_id=share_id, _external=True)
    return jsonify({'share_url': share_url})

@app.route('/download_shared_playlist/<share_id>')
def download_shared_playlist(share_id):
    if share_id not in shared_playlists:
        return render_template('shared_playlist.html', error="Playlist non trovata")
    
    shared_data = shared_playlists[share_id]
    playlist = shared_data['playlist']
    playlist_name = shared_data['name']
    
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
    
    return render_template('shared_playlist.html', playlist=playlist, playlist_name=playlist_name, m3u_content=m3u_content)

@app.route('/get_playlist_history', methods=['GET'])
def get_playlist_history():
    playlist_history = session.get('playlist_history', [])
    # Assicuriamoci che la playlist sia serializzabile
    for item in playlist_history:
        if 'playlist' in item and isinstance(item['playlist'], str):
            item['playlist'] = json.loads(item['playlist'])
    return render_template('playlist_history.html', playlist_history=playlist_history)

if __name__ == '__main__':
    app.run(debug=True)