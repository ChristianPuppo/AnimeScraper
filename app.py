from flask import Flask, render_template, request, jsonify, Response
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin

app = Flask(__name__)

BASE_URL = "https://www.animesaturn.mx"


def search_anime(query):
    search_url = urljoin(BASE_URL, f"/animelist?search={query}")
    response = requests.get(search_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    results = soup.find_all('a', class_='badge-archivio')
    return [{"title": result.text.strip(), "url": urljoin(BASE_URL, result['href']),
             "html": str(result.find_parent('div', class_='item-archivio'))} for result in results]


def get_episodes(anime_url):
    response = requests.get(anime_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    episodes = soup.find_all('a', class_='bottone-ep')
    episode_data = []

    for ep in episodes:
        episode_number = re.search(r'Episodio (\d+)', ep.text)
        episode_data.append({
            "title": ep.text.strip(),
            "url": urljoin(BASE_URL, ep['href']),
            "number": int(episode_number.group(1)) if episode_number else None
        })

    return episode_data


def get_anime_details(anime_url):
    response = requests.get(anime_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')

    details = {}

    # Estrai il titolo
    title_elem = soup.find('h1', class_='title-archivio')
    details['title'] = title_elem.text.strip() if title_elem else None

    # Estrai la valutazione
    rating_elem = soup.find('b', string='Voto:')
    if rating_elem:
        rating_text = rating_elem.find_next(string=True)
        rating_match = re.search(r'([\d.]+)/5', rating_text)
        details['rating'] = float(rating_match.group(1)) if rating_match else None

    # Estrai la thumbnail
    thumbnail_elem = soup.find('img', class_='rounded copertina-archivio')
    details['thumbnail'] = thumbnail_elem['src'] if thumbnail_elem else None

    # Estrai il numero di episodi
    episodes_elem = soup.find('b', string='Episodi:')
    if episodes_elem:
        episodes_text = episodes_elem.find_next(string=True)
        episodes_match = re.search(r'\d+', episodes_text)
        details['episodes'] = int(episodes_match.group()) if episodes_match else None

    return details


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

    except requests.RequestException as e:
        print(f"Errore nell'estrazione dell'URL video: {e}")

    return None


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/search', methods=['POST'])
def search():
    query = request.json['query']
    results = search_anime(query)
    return jsonify(results)


@app.route('/episodes', methods=['POST'])
def episodes():
    anime_url = request.json['anime_url']
    episodes = get_episodes(anime_url)
    return jsonify(episodes)


@app.route('/anime_details', methods=['POST'])
def anime_details():
    anime_url = request.json['anime_url']
    details = get_anime_details(anime_url)
    return jsonify(details)


@app.route('/stream', methods=['POST'])
def stream():
    episode_url = request.json['episode_url']
    streaming_url = get_streaming_url(episode_url)
    if streaming_url:
        video_url = extract_video_url(streaming_url)
        return jsonify({"video_url": video_url, "streaming_url": streaming_url})
    return jsonify({"error": "Impossibile trovare il link dello streaming."})


if __name__ == '__main__':
    app.run(debug=True)