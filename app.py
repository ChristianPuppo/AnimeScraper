from flask import Flask, render_template, request, jsonify, Response
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin
from collections import defaultdict
import os
from dotenv import load_dotenv
from tmdbv3api import TMDb, TV, Season
from fuzzywuzzy import fuzz

app = Flask(__name__)

BASE_URL = "https://www.animesaturn.mx"

# Carica le variabili d'ambiente dal file .env
load_dotenv()

# Configurazione TMDb
tmdb = TMDb()
tmdb.api_key = os.getenv('TMDB_API_KEY')
tmdb.language = 'it'
tv = TV()
season = Season()

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

        italian_title = ep.get('title', '').strip()
        if not italian_title:
            italian_title = ep.text.strip()

        episode_data.append({
            "title": italian_title,
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
        # Rimuovi "(ITA)" e altri suffissi comuni dal titolo per la ricerca
        search_title = re.sub(r'\s*(\(ITA\)|\(SUB ITA\)|\(TV\)|\(OAV\)|\(OVA\))\s*', '', title).strip()
        print(f"DEBUG: Titolo di ricerca modificato: {search_title}")
        
        # Lista di possibili varianti del titolo
        title_variants = [
            search_title,
            re.sub(r'[:\-–].*$', '', search_title).strip(),  # Prendi solo la prima parte del titolo
            ' '.join(search_title.split()[:3]),  # Prendi solo le prime tre parole
            ' '.join(search_title.split()[:2]),  # Prendi solo le prime due parole
            search_title.split(':')[0].strip(),  # Prendi la parte prima dei due punti
        ]
        
        best_match = None
        highest_ratio = 0
        
        for variant in title_variants:
            print(f"DEBUG: Provando variante: {variant}")
            search = tv.search(variant)
            if search:
                for result in search:
                    ratio = fuzz.ratio(result.name.lower(), search_title.lower())
                    if ratio > highest_ratio:
                        highest_ratio = ratio
                        best_match = result

        if best_match and highest_ratio > 60:  # Soglia di somiglianza
            print(f"DEBUG: Serie trovata su TMDb: {best_match.name}")
            details = tv.details(best_match.id)
            seasons = details.seasons
            episodes = []
            for s in seasons:
                print(f"DEBUG: Recuperando dettagli per la stagione {s.season_number}")
                season_details = season.details(best_match.id, s.season_number)
                episodes.extend(season_details.episodes)
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
    m3u_content = "#EXTM3U\n"
    playlist_title = "Playlist Anime"  # Titolo predefinito
    
    for series in playlist:
        series_title = series['title']
        print(f"DEBUG: Cercando metadata per la serie: {series_title}")
        metadata = get_series_metadata(series_title)
        
        if metadata:
            print(f"DEBUG: Metadata trovati per {series_title}")
            italian_title = metadata['title']
            original_title = metadata['original_title']
            description = metadata.get('overview', '').replace('\n', ' ')
            cover_image = metadata.get('poster_path', '')
            year = metadata['first_air_date'][:4] if metadata.get('first_air_date') else ''
            genres = ', '.join(metadata.get('genres', []))
            
            m3u_content += f"\n#EXTINF:-1 group-title=\"{italian_title}\" tvg-logo=\"{cover_image}\",{original_title} ({year})\n"
            m3u_content += f"#EXTGRP:{italian_title}\n"
            m3u_content += f"#EXTDESC:{description}\n"
            m3u_content += f"#EXTGENRE:{genres}\n"
            
            if playlist_title == "Playlist Anime":
                playlist_title = f"Playlist {italian_title}"

            tmdb_episodes = {ep.episode_number: ep.name for ep in metadata['episodes']}
            print(f"DEBUG: Episodi trovati su TMDb: {tmdb_episodes}")
        else:
            print(f"DEBUG: Nessun metadata trovato per {series_title}")
            m3u_content += f"\n#EXTINF:-1 group-title=\"{series_title}\",{series_title}\n"
            m3u_content += f"#EXTGRP:{series_title}\n"
            tmdb_episodes = {}
        
        for i, episode in enumerate(series['episodes'], 1):
            file_name = episode['url'].split('/')[-1]
            episode_number = re.search(r'Ep_(\d+)', file_name)
            if episode_number:
                episode_number = int(episode_number.group(1))
                episode_title = tmdb_episodes.get(episode_number, f"Episodio {episode_number}")
            else:
                episode_title = f"Episodio {i}"
            
            print(f"DEBUG: Titolo episodio {i}: {episode_title}")
            episode_title = f"{episode_title} - {series_title}"
            
            m3u_content += f"#EXTINF:-1,{episode_title}\n"
            m3u_content += f"{episode['url']}\n"
        
        m3u_content += "#EXT-X-ENDLIST\n\n"  # Separatore tra serie
    
    print(f"DEBUG: Contenuto M3U generato:\n{m3u_content}")
    return Response(
        m3u_content,
        mimetype='text/plain',
        headers={'Content-Disposition': f'attachment; filename="{playlist_title}.m3u"'}
    )

if __name__ == '__main__':
    app.run(debug=True)