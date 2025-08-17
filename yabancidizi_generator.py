import requests
import re
import sys
from typing import Dict, List, Optional, Set

# --- Statik Konfigürasyon ---
DEFAULT_BASE_URL = 'https://yabancidizi.watch' 
SOURCE_URL = 'https://raw.githubusercontent.com/kerimmkirac/cs-kerim/master/YabanciDizi/src/main/kotlin/com/kerimmkirac/YabanciDizi.kt'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://yabancidizi.watch/'
}

def get_dynamic_base_url() -> str:
    """
    Kotlin kaynağından dinamik olarak ana URL'yi çeker.
    Bu, sitenin adresi değişse bile betiğin çalışmasını sağlar.
    """
    try:
        print("Dinamik ana URL GitHub'dan alınıyor...", file=sys.stderr)
        response = requests.get(SOURCE_URL, timeout=15)
        response.raise_for_status()
        content = response.text
        if match := re.search(r'override\s+var\s+mainUrl\s*=\s*"([^"]+)"', content):
            url = match.group(1)
            print(f"Dinamik URL başarıyla bulundu: {url}", file=sys.stderr)
            return url
        else:
            print("Dinamik URL deseni bulunamadı.", file=sys.stderr)
    except requests.RequestException as e:
        print(f"GitHub'dan dinamik URL alınamadı: {e}", file=sys.stderr)
    
    print(f"Varsayılan URL kullanılıyor: {DEFAULT_BASE_URL}", file=sys.stderr)
    return DEFAULT_BASE_URL

def fetch_json(url: str) -> Optional[Dict]:
    """
    Verilen URL'den JSON verisi çeker ve hataları yönetir.
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as http_err:
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
    
    # Sadece geçerli m3u8 linklerini işle
    if not stream_url or not isinstance(stream_url, str) or not stream_url.endswith('.m3u8'):
        return ''

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
    processed_series_ids: Set[int] = set()

    print("Ana sayfadan diziler alınıyor...", file=sys.stderr)
    home_url = f"{base_url}/api/home"
    home_data = fetch_json(home_url)

    if not home_data:
        print("Ana sayfa verisi alınamadı. Betik sonlandırılıyor.", file=sys.stderr)
        return

    # Ana sayfadaki tüm dizi listelerini topla
    all_series: List[Dict] = []
    # Ana sayfada dizilerin bulunduğu olası anahtarlar
    series_keys = ['popular_series', 'latest_series', 'series'] 
    for key in series_keys:
        if key in home_data and isinstance(home_data[key], list):
            all_series.extend(home_data[key])
            
    if not all_series:
        print("Hiç dizi bulunamadı. API yapısı değişmiş olabilir.", file=sys.stderr)
        return

    print(f"Toplam {len(all_series)} dizi girişi bulundu. Bölümler işleniyor...", file=sys.stderr)

    for series_summary in all_series:
        series_id = series_summary.get('id')
        series_title = series_summary.get('title', 'Bilinmeyen Dizi')
        
        if not series_id or series_id in processed_series_ids:
            continue # ID yoksa veya bu dizi zaten işlendiyse atla

        print(f"-> Dizi işleniyor: {series_title} (ID: {series_id})", file=sys.stderr)
        
        series_detail_url = f"{base_url}/api/dizi/{series_id}"
        seasons_data = fetch_json(series_detail_url)
        
        if not seasons_data or not isinstance(seasons_data, list):
            print(f"  - {series_title} için sezon verisi alınamadı veya format yanlış.", file=sys.stderr)
            continue
        
        # Poster bilgisini detaydan almak daha güvenilir olabilir
        series_poster = series_summary.get('poster', '')

        for season in seasons_data:
            season_num = season.get('season')
            episodes = season.get('episodes', [])
            
            if not episodes or season_num is None:
                continue

            print(f"  - Sezon {season_num} için {len(episodes)} bölüm bulundu.", file=sys.stderr)
            for episode in episodes:
                m3u_lines.append(process_episode(episode, series_title, series_poster, season_num))
        
        processed_series_ids.add(series_id) # Bu diziyi işlendi olarak işaretle

    output_filename = 'yabancidizi_full.m3u'
    with open(output_filename, 'w', encoding='utf-8') as f:
        f.write(''.join(m3u_lines))
        
    content_count = len(m3u_lines) - 1
    if content_count > 0:
        print(f"\n'{output_filename}' dosyası başarıyla oluşturuldu!", file=sys.stderr)
        print(f"Toplam {content_count} geçerli yayın linki eklendi.", file=sys.stderr)
    else:
        print(f"\n'{output_filename}' dosyası oluşturuldu ancak içine eklenecek geçerli yayın bulunamadı.", file=sys.stderr)

if __name__ == "__main__":
    main()