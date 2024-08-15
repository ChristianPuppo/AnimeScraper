import requests
from bs4 import BeautifulSoup
import re
import subprocess
import os
from urllib.parse import urljoin
from colorama import init, Fore, Style
import webbrowser

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

        # Cerca un iframe nella pagina
        iframe = soup.find('iframe')
        if iframe and 'src' in iframe.attrs:
            iframe_src = iframe['src']
            iframe_response = requests.get(iframe_src)
            iframe_response.raise_for_status()
            video_pattern = r'(https?://.*?\.(?:m3u8|mp4))'

            # Cerca negli elementi script del iframe
            iframe_soup = BeautifulSoup(iframe_response.text, 'html.parser')
            for script in iframe_soup.find_all('script'):
                match = re.search(video_pattern, str(script))
                if match:
                    return match.group(0)

            # Cerca direttamente nel testo del iframe
            match = re.search(video_pattern, iframe_response.text)
            if match:
                return match.group(0)

        # Cerca direttamente nella pagina originale se non si trova nell'iframe
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

    if len(episodes) > 1:
        print(f"{Fore.GREEN}Episodi disponibili per {selected_anime}:")
        print_menu([ep_title for ep_title, _ in episodes])
        ep_choice = get_user_choice("Seleziona il numero dell'episodio desiderato:", episodes)
        _, episode_url = episodes[ep_choice]
    else:
        print(f"{Fore.BLUE}Film trovato. Procedendo con la riproduzione.")
        _, episode_url = episodes[0]

    streaming_url = get_streaming_url(episode_url)

    if not streaming_url:
        print(f"{Fore.RED}Impossibile trovare il link dello streaming.")
        return

    video_url = extract_video_url(streaming_url)

    if video_url:
        print(f"{Fore.GREEN}URL del video trovato: {video_url}")
        play_video(video_url)
    else:
        print(f"{Fore.YELLOW}Nessun URL video trovato.")
        print(f"{Fore.YELLOW}Link streaming: {streaming_url}")
        if input(f"{Fore.YELLOW}Vuoi aprire questo link in VLC? (s/n): ").lower() == 's':
            play_video(streaming_url)

    print(
        f"{Fore.CYAN}Se VLC non si è avviato automaticamente, copia il link e usalo in VLC.")


if __name__ == "__main__":
    main()