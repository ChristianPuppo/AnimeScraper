from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin

app = Flask(__name__)

BASE_URL = "https://www.animesaturn.mx"


def get_soup(url):
    response = requests.get(url)
    response.raise_for_status()
    return BeautifulSoup(response.text, 'html.parser')


def extract_thumbnail(element):
    img = element.find('img', class_='copertina-archivio')
    return img['src'] if img else None


def extract_rating(soup):
    rating_element = soup.find('b', string='Voto:')
    if rating_element:
        rating_text = rating_element.find_next(string=True)
        match = re.search(r'(\d+\.\d+)/5', rating_text)
        if match:
            return float(match.group(1))
    return None


@app.route('/search', methods=['POST'])
def search():
    query = request.json['query']
    search_url = urljoin(BASE_URL, f"/animelist?search={query}")

    try:
        soup = get_soup(search_url)
        results = soup.find_all('div', class_='anime-card')

        anime_list = []
        for result in results:
            title_element = result.find('a', class_='badge-archivio')
            if title_element:
                title = title_element.text.strip()
                url = urljoin(BASE_URL, title_element['href'])
                thumbnail = extract_thumbnail(result)

                anime_list.append({
                    'title': title,
                    'url': url,
                    'thumbnail': thumbnail
                })

        return jsonify(anime_list)
    except requests.RequestException as e:
        return jsonify({'error': str(e)}), 500


@app.route('/search_suggestions', methods=['POST'])
def search_suggestions():
    query = request.json['query']
    search_url = urljoin(BASE_URL, f"/animelist?search={query}")

    try:
        soup = get_soup(search_url)
        results = soup.find_all('a', class_='badge-archivio')[:10]  # Limit to 10 suggestions

        suggestions = [{'title': result.text.strip(), 'url': urljoin(BASE_URL, result['href'])} for result in results]
        return jsonify(suggestions)
    except requests.RequestException as e:
        return jsonify({'error': str(e)}), 500


@app.route('/episodes', methods=['POST'])
def episodes():
    anime_url = request.json['anime_url']

    try:
        soup = get_soup(anime_url)
        episode_links = soup.find_all('a', class_='bottone-ep')
        rating = extract_rating(soup)

        episodes_data = []
        for link in episode_links:
            episodes_data.append({
                'title': link.text.strip(),
                'url': urljoin(BASE_URL, link['href'])
            })

        return jsonify({
            'episodes': episodes_data,
            'rating': rating
        })
    except requests.RequestException as e:
        return jsonify({'error': str(e)}), 500


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


@app.route('/stream', methods=['POST'])
def stream():
    episode_url = request.json['episode_url']

    try:
        soup = get_soup(episode_url)
        streaming_link = soup.find('a', href=lambda href: href and 'watch?file=' in href)
        if streaming_link:
            streaming_url = urljoin(BASE_URL, streaming_link['href'])
            video_url = extract_video_url(streaming_url)
            if video_url:
                return jsonify({'video_url': video_url})
            else:
                return jsonify({'error': 'Impossibile trovare l\'URL del video'}), 404
        else:
            return jsonify({'error': 'Link di streaming non trovato'}), 404
    except requests.RequestException as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)