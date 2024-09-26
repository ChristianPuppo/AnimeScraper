from flask import Flask, render_template, request, jsonify, Response
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin
from collections import defaultdict
from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport

app = Flask(__name__)

BASE_URL = "https://www.animesaturn.mx"

# Configurazione del client GraphQL per AniList
anilist_transport = RequestsHTTPTransport(url='https://graphql.anilist.co')
anilist_client = Client(transport=anilist_transport, fetch_schema_from_transport=True)

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

        # Cerchiamo il titolo italiano dell'episodio
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

def get_anilist_metadata(title):
    query = gql('''
    query ($search: String) {
        Media (search: $search, type: ANIME) {
            id
            title {
                romaji
                english
            }
            description
            episodes
            coverImage {
                large
            }
            startDate {
                year
                month
                day
            }
            genres
        }
    }
    ''')
    
    try:
        result = anilist_client.execute(query, variable_values={'search': title})
        return result['Media']
    except Exception as e:
        print(f"Errore nel recupero dei metadata da AniList: {e}")
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
    
    for series in playlist:
        series_title = series['title']
        metadata = get_anilist_metadata(series_title)
        
        if metadata:
            english_title = metadata['title']['english'] or metadata['title']['romaji']
            description = metadata.get('description', '').replace('\n', ' ')
            cover_image = metadata['coverImage']['large']
            year = metadata['startDate']['year']
            genres = ', '.join(metadata['genres'])
            
            m3u_content += f"\n#EXTINF:-1 group-title=\"{series_title}\" tvg-logo=\"{cover_image}\",{english_title} ({year})\n"
            m3u_content += f"#EXTGRP:{series_title}\n"
            m3u_content += f"#EXTDESC:{description}\n"
            m3u_content += f"#EXTGENRE:{genres}\n"
        else:
            m3u_content += f"\n#EXTINF:-1 group-title=\"{series_title}\",{series_title}\n"
            m3u_content += f"#EXTGRP:{series_title}\n"
        
        for i, episode in enumerate(series['episodes'], 1):
            # Usiamo il titolo italiano dell'episodio
            m3u_content += f"#EXTINF:-1,Episodio {i}: {episode['title']}\n"
            m3u_content += f"{episode['url']}\n"
        
        m3u_content += "#EXT-X-ENDLIST\n\n"  # Separatore tra serie
    
    return Response(
        m3u_content,
        mimetype='text/plain',
        headers={'Content-Disposition': 'attachment; filename=playlist.m3u'}
    )

if __name__ == '__main__':
    app.run(debug=True)