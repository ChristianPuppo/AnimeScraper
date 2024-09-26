import requests
from bs4 import BeautifulSoup
import re
import subprocess
import os
from urllib.parse import urljoin
from colorama import init, Fore, Style
import webbrowser
import aiohttp
import asyncio

init(autoreset=True)

BASE_URL = "https://www.animesaturn.mx"


def search_anime(query):
    search_url = urljoin(BASE_URL, f"/animelist?search={query}")
    response = requests.get(search_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    results = soup.find_all('a', class_='badge-archivio')
    return [(result.text.strip(), urljoin(BASE_URL, result['href'])) for result in results]


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

        episode_data.append({
            "title": ep.text.strip(),
            "url": urljoin(BASE_URL, ep['href']),
            "thumbnail": thumbnail_url
        })

    return episode_data


async def fetch(session, url):
    async with session.get(url) as response:
        return await response.text()


async def get_streaming_url_async(session, episode_url):
    html = await fetch(session, episode_url)
    soup = BeautifulSoup(html, 'html.parser')
    streaming_link = soup.find('a', href=lambda href: href and 'watch?file=' in href)
    if streaming_link:
        return urljoin(BASE_URL, streaming_link['href'])
    return None


async def extract_video_url_async(session, url):
    try:
        html = await fetch(session, url)
        soup = BeautifulSoup(html, 'html.parser')

        # Cerca un iframe nella pagina
        iframe = soup.find('iframe')
        if iframe and 'src' in iframe.attrs:
            iframe_src = iframe['src']
            iframe_html = await fetch(session, iframe_src)
            iframe_soup = BeautifulSoup(iframe_html, 'html.parser')
            video_pattern = r'(https?://.*?\.(?:m3u8|mp4))'

            # Cerca negli elementi script del iframe
            for script in iframe_soup.find_all('script'):
                match = re.search(video_pattern, str(script))
                if match:
                    return match.group(0)

            # Cerca direttamente nel testo del iframe
            match = re.search(video_pattern, iframe_html)
            if match:
                return match.group(0)

        # Cerca direttamente nella pagina originale se non si trova nell'iframe
        video_pattern = r'(https?://.*?\.(?:m3u8|mp4))'
        for script in soup.find_all('script'):
            match = re.search(video_pattern, str(script))
            if match:
                return match.group(0)

        match = re.search(video_pattern, html)
        if match:
            return match.group(0)

    except Exception as e:
        print(f"{Fore.RED}Errore nell'estrazione dell'URL video: {e}")

    return None


async def get_video_urls(episode_urls):
    async with aiohttp.ClientSession() as session:
        tasks = []
        for episode_url in episode_urls:
            tasks.append(get_streaming_url_async(session, episode_url))
        streaming_urls = await asyncio.gather(*tasks)

        tasks = []
        for streaming_url in streaming_urls:
            if streaming_url:
                tasks.append(extract_video_url_async(session, streaming_url))
        video_urls = await asyncio.gather(*tasks)

    return video_urls


def play_video(video_url):
    try:
        # Costruisce il comando per aprire VLC su macOS
        vlc_command = f"/Applications/VLC.app/Contents/MacOS/VLC --play-and-exit '{video_url}'"
        subprocess.run(vlc_command, shell=True)
        print(f"{Fore.GREEN}Avvio di VLC con il link: {video_url}")
    except Exception as e:
        print(f"{Fore.RED}Errore nell'avvio di VLC: {e}")


def print_menu(options):
    for i, option in enumerate(options, 1):
        print(f"{Fore.CYAN}{i}. {option}")


def get_user_choice(prompt, options):
    while True:
        try:
            choice = int(input(f"{Fore.YELLOW}{prompt} "))
            if 1 <= choice <= len(options):
                return choice - 1
            print(f"{Fore.RED}Scelta non valida. Riprova.")
        except ValueError:
            print(f"{Fore.RED}Inserisci un numero valido.")


def main():
    print(f"{Fore.MAGENTA}=== AnimeSaturn Viewer ===")

    query = input(f"{Fore.YELLOW}Quale anime vuoi vedere? ")
    results = search_anime(query)

    if not results:
        print(f"{Fore.RED}Nessun risultato trovato.")
        return

    print(f"{Fore.GREEN}Risultati della ricerca:")
    print_menu([title for title, _ in results])

    choice = get_user_choice("Seleziona il numero dell'anime desiderato:", results)
    selected_anime, anime_url = results[choice]

    episodes = get_episodes(anime_url)
    episode_urls = [ep['url'] for ep in episodes]

    if len(episodes) > 1:
        print(f"{Fore.GREEN}Episodi disponibili per {selected_anime}:")
        print_menu([ep['title'] for ep in episodes])
        ep_choice = get_user_choice("Seleziona il numero dell'episodio desiderato:", episodes)
        episode_urls = [episode_urls[ep_choice]]

    video_urls = asyncio.run(get_video_urls(episode_urls))

    for video_url in video_urls:
        if video_url:
            print(f"{Fore.GREEN}URL del video trovato: {video_url}")
            play_video(video_url)
        else:
            print(f"{Fore.YELLOW}Nessun URL video trovato.")

    print(
        f"{Fore.CYAN}Se VLC non si è avviato automaticamente, copia il link e usalo in VLC.")


if __name__ == "__main__":
    main()