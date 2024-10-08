import requests
from bs4 import BeautifulSoup
import re
import subprocess
import os
from urllib.parse import urljoin
from colorama import init, Fore, Style
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

init(autoreset=True)

BASE_URL = "https://www.animesaturn.cx"
MAX_CONCURRENT_DOWNLOADS = 5

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
    return [(ep.text.strip(), urljoin(BASE_URL, ep['href'])) for ep in episodes]

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
        print(f"{Fore.RED}Errore nell'estrazione dell'URL video: {e}")

    return None

def download_video(video_url, output_path):
    try:
        if video_url.endswith('.mp4'):
            print(f"{Fore.GREEN}Scaricamento episodio: {os.path.basename(output_path)}")
            response = requests.get(video_url, stream=True)
            total_size = int(response.headers.get('content-length', 0))
            block_size = 1024 * 1024  # 1 MB

            with open(output_path, 'wb') as file:
                for chunk in response.iter_content(chunk_size=block_size):
                    if chunk:
                        file.write(chunk)

        elif video_url.endswith('.m3u8'):
            print(f"{Fore.GREEN}Scaricamento episodio: {os.path.basename(output_path)}")
            subprocess.run(['ffmpeg', '-i', video_url, '-c', 'copy', output_path], check=True)

        return output_path

    except (requests.RequestException, subprocess.CalledProcessError) as e:
        print(f"{Fore.RED}Errore durante il download del video: {e}")
        return None

def download_episode(episode_num, episode_title, episode_url, output_dir):
    streaming_url = get_streaming_url(episode_url)
    video_url = extract_video_url(streaming_url)
    if video_url:
        output_filename = f"Episodio {episode_num}.mp4"
        output_path = os.path.join(output_dir, output_filename)
        downloaded_path = download_video(video_url, output_path)
        if downloaded_path:
            print(f"{Fore.GREEN}Episodio {episode_num} - {episode_title} scaricato con successo.")
            return True
    else:
        print(f"{Fore.YELLOW}Impossibile trovare l'URL video per l'episodio {episode_num} - {episode_title}.")
    return False

def download_season_or_range(episodes, output_dir):
    print(f"{Fore.YELLOW}Vuoi scaricare l'intera stagione o un range di episodi?")
    print_menu(["Intera stagione", "Range di episodi"])
    choice = get_user_choice("Seleziona un'opzione:", ["Intera stagione", "Range di episodi"])

    if choice == 0:  # Intera stagione
        episode_range = range(len(episodes))
    else:  # Range di episodi
        start = int(input(f"{Fore.YELLOW}Inserisci il numero dell'episodio di inizio: ")) - 1
        end = int(input(f"{Fore.YELLOW}Inserisci il numero dell'episodio di fine: "))
        episode_range = range(start, end)

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS) as executor:
        futures = []
        for i in episode_range:
            ep_num, (ep_title, ep_url) = i + 1, episodes[i]
            future = executor.submit(download_episode, ep_num, ep_title, ep_url, output_dir)
            futures.append(future)

        completed = 0
        for future in as_completed(futures):
            completed += 1
            print(f"{Fore.CYAN}Progresso: {completed}/{len(futures)} episodi completati.")

    print(f"{Fore.GREEN}Tutti gli episodi selezionati sono stati scaricati!")

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
    print(f"{Fore.MAGENTA}=== AnimeSaturn Downloader ===")

    query = input(f"{Fore.YELLOW}Quale anime vuoi scaricare? ")
    results = search_anime(query)

    if not results:
        print(f"{Fore.RED}Nessun risultato trovato.")
        return

    print(f"{Fore.GREEN}Risultati della ricerca:")
    print_menu([title for title, _ in results])

    choice = get_user_choice("Seleziona il numero dell'anime desiderato:", results)
    selected_anime, anime_url = results[choice]
    output_dir = os.path.join(os.path.dirname(__file__), selected_anime)
    os.makedirs(output_dir, exist_ok=True)

    episodes = get_episodes(anime_url)

    if len(episodes) > 1:
        print(f"{Fore.GREEN}Episodi disponibili per {selected_anime}:")
        print_menu([ep_title for ep_title, _ in episodes])
        download_season_or_range(episodes, output_dir)
    else:
        print(f"{Fore.BLUE}Film trovato. Procedendo con il download.")
        _, episode_url = episodes[0]
        download_episode(1, selected_anime, episode_url, output_dir)

    print(f"{Fore.CYAN}I video sono stati scaricati nella cartella: {output_dir}")

if __name__ == "__main__":
    main()