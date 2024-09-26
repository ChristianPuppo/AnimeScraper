from quart import Quart, render_template, request, jsonify, Response
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin
import asyncio
from Scraper import get_episodes, get_video_urls

app = Quart(__name__)

BASE_URL = "https://www.animesaturn.mx"

def search_anime(query):
    search_url = urljoin(BASE_URL, f"/animelist?search={query}")
    response = requests.get(search_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    results = soup.find_all('a', class_='badge-archivio')
    return [{"title": result.text.strip(), "url": urljoin(BASE_URL, result['href'])} for result in results]

@app.route('/')
async def index():
    return await render_template('index.html')

@app.route('/search', methods=['POST'])
async def search():
    query = (await request.form)['query']
    results = search_anime(query)
    return jsonify(results)

@app.route('/search_suggestions', methods=['POST'])
async def search_suggestions():
    query = (await request.form)['query']
    results = search_anime(query)[:10]  # Limita a 10 suggerimenti
    return jsonify(results)

@app.route('/episodes', methods=['POST'])
async def episodes():
    anime_url = (await request.form)['anime_url']
    print(f"Richiesta per gli episodi di: {anime_url}")
    episodes = get_episodes(anime_url)
    print(f"Episodi trovati: {episodes}")
    return jsonify(episodes)

@app.route('/stream', methods=['POST'])
async def stream():
    episode_url = (await request.form)['episode_url']
    print(f"Richiesta per lo streaming dell'episodio: {episode_url}")
    video_urls = await get_video_urls([episode_url])
    if video_urls and video_urls[0]:
        print(f"URL video estratto: {video_urls[0]}")
        return jsonify({"video_url": video_urls[0]})
    print("Impossibile trovare il link dello streaming.")
    return jsonify({"error": "Impossibile trovare il link dello streaming."})

@app.route('/save_playlist', methods=['POST'])
async def save_playlist():
    playlist = (await request.json)['playlist']
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