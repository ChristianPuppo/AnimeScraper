from flask import Flask, render_template, request, jsonify, Response
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin
from Scraper import get_episodes, get_streaming_url, extract_video_url

app = Flask(__name__)

BASE_URL = "https://www.animesaturn.mx"

def search_anime(query):
    search_url = urljoin(BASE_URL, f"/animelist?search={query}")
    response = requests.get(search_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    results = soup.find_all('a', class_='badge-archivio')
    return [{"title": result.text.strip(), "url": urljoin(BASE_URL, result['href'])} for result in results]

def get_episodes(anime_url):
    episodes = get_episodes(anime_url)
    return jsonify(episodes)

def get_streaming_url(episode_url):
    streaming_url = get_streaming_url(episode_url)
    if streaming_url:
        video_url = extract_video_url(streaming_url)
        return jsonify({"video_url": video_url, "streaming_url": streaming_url})
    return jsonify({"error": "Impossibile trovare il link dello streaming."})

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
    print(f"Salvataggio della playlist: {playlist}")
    m3u_content = "#EXTM3U\n"
    for series in playlist:
        for episode in series['episodes']:
            m3u_content += f"#EXTINF:-1,{series['title']} - {episode['title']}\n{episode['url']}\n"
    return Response(
        m3u_content,
        mimetype='text/plain',
        headers={'Content-Disposition': 'attachment; filename=playlist.m3u'}
    )

if __name__ == '__main__':
    app.run(debug=True)