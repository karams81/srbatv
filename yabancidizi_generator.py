import requests
import re
import os
import sys
from typing import Dict, List, Optional

# --- Statik Konfigürasyon ---
# GitHub'dan dinamik olarak alınamazsa kullanılacak varsayılan URL
DEFAULT_BASE_URL = 'https://yabancidizi.watch' 
# Kotlin dosyasının URL'si
SOURCE_URL = 'https://raw.githubusercontent.com/kerimmkirac/cs-kerim/master/YabanciDizi/src/main/kotlin/com/kerimmkirac/YabanciDizi.kt'
# İstekler için kullanılacak başlıklar
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
    'Referer': 'https://yabancidizi.watch/'
}
# Sayfa başına denenecek maksimum dizi/bölüm sayısı (API limiti belirsiz olduğu için)
MAX_PAGES_TO_TRY = 15 

def get_dynamic_base_url() -> str:
    """
    Kotlin kaynağından dinamik olarak ana URL'yi çeker.
    Bu, sitenin adresi değişse bile betiğin çalışmasını sağlar.
    """
    try:
        response = requests.get(SOURCE_URL, timeout=15)
        response.raise_for_status()
        content = response.text
        # Kotlin kodundaki 'override var mainUrl = "..."' ifadesini arar
        if match := re.search(r'override\s+var\s+mainUrl\s*=\s*"([^"]+)"', content):
            url = match.group(1)
            print(f"Dinamik URL başarıyla bulundu: {url}", file=sys.stderr)
            return url
    except requests.RequestException as e:
        print(f"GitHub'dan dinamik URL alınamadı: {e}", file=sys.stderr)
    
    print(f"Varsayılan URL kullanılıyor: {DEFAULT_BASE_URL}", file=sys.stderr)
    return DEFAULT_BASE_URL

def fetch_json(url: str) -> Optional[List[Dict]]:
    """
    Verilen URL'den JSON verisi çeker ve hataları yönetir.
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        # 404 gibi hatalar genellikle sayfa sonunu belirtir, bu yüzden sessiz kal
        if response.status_code != 404:
            print(f"HTTP Hatası ({url}): {http_err}", file=sys.stderr)
    except requests.RequestException as e:
        print(f"API isteği hatası ({url}): {e}", file=sys.stderr)
    return None

def process_episode(episode: Dict, series_title: str, series_poster: str, season_num: int) -> str:
    """
    Tek bir bölüm verisini M3U formatına dönüştürür.
    """
    episode_title = episode.get('title', f"Bölüm {episode.get('episode')}")
    stream_url = episode.get('streamUrl', '')
    
    if not stream_url or not stream_url.endswith('.m3u8'):
        return ''

    # M3U için bölüm bilgilerini formatla
    group_title = f"{series_title} | Sezon {season_num}"
    full_title = f"{series_title} - S{season_num:02d}E{episode.get('episode', 0):02d} - {episode_title}"
    
    return (
        f'#EXTINF:-1 tvg-id="{episode.get("id", "")}" tvg-name="{full_title}" '
        f'tvg-logo="{series_poster}" group-title="{group_title}",{full_title}\n'
        f'#EXTVLCOPT:http-user-agent={HEADERS["User-Agent"]}\n'
        f'#EXTVLCOPT:http-referrer={HEADERS["Referer"]}\n'
        f'{stream_url}\n'
    )

def main():
    """
    Ana fonksiyon: Dizileri, sezonları ve bölümleri alıp M3U dosyasını oluşturur.
    """
    base_url = get_dynamic_base_url()
    m3u_lines = ["#EXTM3U\n"]

    print("Diziler alınıyor...", file=sys.stderr)
    
    # --- Tüm Dizileri Al ---
    all_series = []
    for page in range(MAX_PAGES_TO_TRY):
        series_url = f"{base_url}/api/dizi?page={page}"
        series_data = fetch_json(series_url)
        if not series_data:
            print(f"{page}. sayfadan sonra dizi bulunamadı. Dizi alımı tamamlandı.", file=sys.stderr)
            break
        all_series.extend(series_data)

    print(f"Toplam {len(all_series)} dizi bulundu. Bölümler işleniyor...", file=sys.stderr)

    # --- Her Dizi İçin Sezonları ve Bölümleri İşle ---
    for series in all_series:
        series_id = series.get('id')
        series_title = series.get('title', 'Bilinmeyen Dizi')
        series_poster = series.get('poster', '')
        
        if not series_id:
            continue

        print(f"  -> Dizi işleniyor: {series_title}", file=sys.stderr)
        
        # Sezonları al (API'de sezonlar için ayrı bir endpoint yok, doğrudan bölümler alınıyor)
        seasons_url = f"{base_url}/api/dizi/{series_id}"
        seasons_data = fetch_json(seasons_url)
        
        if not seasons_data or not isinstance(seasons_data, list):
            continue
            
        for season in seasons_data:
            season_num = season.get('season', 0)
            episodes = season.get('episodes', [])
            
            if not episodes:
                continue

            print(f"    -> Sezon {season_num} için {len(episodes)} bölüm bulundu.", file=sys.stderr)
            for episode in episodes:
                m3u_lines.append(process_episode(episode, series_title, series_poster, season_num))

    # --- M3U Dosyasını Yaz ---
    output_filename = 'yabancidizi_full.m3u'
    with open(output_filename, 'w', encoding='utf-8') as f:
        f.write(''.join(m3u_lines))
        
    print(f"\n'{output_filename}' dosyası başarıyla oluşturuldu!", file=sys.stderr)
    print(f"Toplam {len(m3u_lines) - 1} geçerli yayın linki eklendi.", file=sys.stderr)


if __name__ == "__main__":
    main()