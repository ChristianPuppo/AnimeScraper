from flask import Flask, render_template, request, jsonify, Response
import asyncio
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin
from Scraper import get_episodes, get_video_urls, search_anime

app = Flask(__name__)

BASE_URL = "https://www.animesaturn.mx"

def run_async(func):
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))
    return wrapper

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    @run_async
    async def async_search():
        query = request.form['query']
        results = await search_anime(query)
        return jsonify(results)
    return async_search()

@app.route('/search_suggestions', methods=['POST'])
def search_suggestions():
    @run_async
    async def async_search_suggestions():
        query = request.form['query']
        results = await search_anime(query)
        return jsonify(results[:10])  # Limita a 10 suggerimenti
    return async_search_suggestions()

@app.route('/episodes', methods=['POST'])
def episodes():
    @run_async
    async def async_episodes():
        anime_url = request.form['anime_url']
        print(f"Richiesta per gli episodi di: {anime_url}")
        episodes = await get_episodes(anime_url)
        print(f"Episodi trovati: {episodes}")
        return jsonify(episodes)
    return async_episodes()

@app.route('/stream', methods=['POST'])
def stream():
    @run_async
    async def async_stream():
        episode_url = request.form['episode_url']
        print(f"Richiesta per lo streaming dell'episodio: {episode_url}")
        video_urls = await get_video_urls([episode_url])
        if video_urls and video_urls[0]:
            print(f"URL video estratto: {video_urls[0]}")
            return jsonify({"video_url": video_urls[0]})
        print("Impossibile trovare il link dello streaming.")
        return jsonify({"error": "Impossibile trovare il link dello streaming."})
    return async_stream()

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