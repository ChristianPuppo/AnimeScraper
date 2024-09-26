from flask import Flask, render_template, request, jsonify, Response
import asyncio
from Scraper import search_anime, get_episodes, get_video_urls

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    query = request.form['query']
    results = asyncio.run(search_anime(query))
    return jsonify(results)

@app.route('/episodes', methods=['POST'])
def episodes():
    anime_url = request.form['anime_url']
    print(f"Richiesta per gli episodi di: {anime_url}")
    episodes = asyncio.run(get_episodes(anime_url))
    print(f"Episodi trovati: {episodes}")
    return jsonify(episodes)

@app.route('/stream', methods=['POST'])
def stream():
    episode_url = request.form['episode_url']
    print(f"Richiesta per lo streaming dell'episodio: {episode_url}")
    episodes = [{"url": episode_url}]
    video_urls = asyncio.run(get_video_urls(episodes))
    if video_urls[0]['url']:
        print(f"URL video estratto: {video_urls[0]['url']}")
        return jsonify({"video_url": video_urls[0]['url']})
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