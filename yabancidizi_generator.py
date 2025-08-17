import cloudscraper
import re
import sys
from typing import Dict, List, Optional, Set

# --- Konfigürasyon ---
FALLBACK_BASE_URL = 'https://yabancidizi.so' 
SOURCE_URL = 'https://raw.githubusercontent.com/fsamet/cs-Kekik/master/YabanciDizi/src/main/kotlin/com/nikyokki/YabanciDizi.kt'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': f'{FALLBACK_BASE_URL}/' 
}
# Öncelik verilecek player'ların sırası
PLAYER_PRIORITY = ["Mac", "Vidmoly"]
# Kaç sayfayı kontrol edeceğimiz (site çok fazla sayfa döndürebilir)
MAX_PAGES_TO_SCAN = 25

scraper = cloudscraper.create_scraper()

def get_dynamic_base_url() -> str:
    """Kotlin kaynağından dinamik olarak ana URL'yi çeker."""
    try:
        print("Dinamik ana URL GitHub'dan alınıyor...", file=sys.stderr)
        response = scraper.get(SOURCE_URL, timeout=15)
        response.raise_for_status()
        content = response.text
        if match := re.search(r'override\s+var\s+mainUrl\s*=\s*"([^"]+)"', content):
            url = match.group(1).strip('/')
            print(f"Dinamik URL başarıyla bulundu: {url}", file=sys.stderr)
            HEADERS['Referer'] = f'{url}/'
            return url
    except Exception as e:
        print(f"GitHub'dan dinamik URL alınamadı: {e}", file=sys.stderr)
    
    print(f"Varsayılan URL kullanılıyor: {FALLBACK_BASE_URL}", file=sys.stderr)
    return FALLBACK_BASE_URL

def main():
    """Ana fonksiyon: M3U dosyasını oluşturur."""
    base_url = get_dynamic_base_url()
    m3u_lines = ["#EXTM3U\n"]
    processed_series_ids: Set[int] = set()

    print("Diziler sayfa sayfa alınıyor...", file=sys.stderr)
    all_series: List[Dict] = []
    for page in range(MAX_PAGES_TO_SCAN):
        try:
            print(f"Sayfa {page} taranıyor...", file=sys.stderr)
            series_url = f"{base_url}/api/dizi?page={page}"
            series_response = scraper.get(series_url, headers=HEADERS, timeout=20)
            series_response.raise_for_status()
            series_data = series_response.json()
            
            if not series_data or not isinstance(series_data, list):
                print(f"Sayfa {page} boş veya geçersiz. Tarama tamamlandı.", file=sys.stderr)
                break
            
            all_series.extend(series_data)
        except Exception as e:
            print(f"Sayfa {page} alınırken hata oluştu: {e}. Tarama tamamlandı.", file=sys.stderr)
            break

    print(f"Toplam {len(all_series)} dizi girişi bulundu. Bölümler işleniyor...", file=sys.stderr)

    for series_summary in all_series:
        series_id = series_summary.get('id')
        if not series_id or series_id in processed_series_ids:
            continue

        series_title = series_summary.get('title', 'Bilinmeyen Dizi')
        print(f"\n-> Dizi işleniyor: {series_title} (ID: {series_id})", file=sys.stderr)
        
        try:
            series_detail_url = f"{base_url}/api/dizi/{series_id}"
            seasons_data = scraper.get(series_detail_url, headers=HEADERS, timeout=20).json()
        except Exception:
            print(f"  - {series_title} için sezon verisi alınamadı.", file=sys.stderr)
            continue

        if not isinstance(seasons_data, list):
            continue

        for season in seasons_data:
            episodes = season.get('episodes', [])
            season_num = season.get('season', 0)
            
            for episode in episodes:
                sources = episode.get('sources', [])
                if not sources: continue

                final_url = None
                # Önce öncelikli player'ları ara
                for player_name in PLAYER_PRIORITY:
                    for source in sources:
                        if source.get('player') == player_name:
                            final_url = source.get('url')
                            break
                    if final_url:
                        break
                
                # Öncelikli player bulunamazsa ilk bulduğunu al
                if not final_url and sources:
                    final_url = sources[0].get('url')

                if final_url:
                    episode_title = episode.get('title', f"Bölüm {episode.get('episode')}")
                    series_poster = series_summary.get('poster', '')
                    group_title = f"{series_title} | Sezon {season_num}"
                    full_title = f"{series_title} - S{season_num:02d}E{episode.get('episode', 0):02d} - {episode_title}"
                    
                    m3u_lines.append(
                        f'#EXTINF:-1 tvg-id="{episode.get("id", "")}" tvg-name="{full_title}" '
                        f'tvg-logo="{series_poster}" group-title="{group_title}",{full_title}\n'
                        # İsteğiniz üzerine doğrudan embed linkini ekliyoruz
                        f'{final_url}\n'
                    )

        processed_series_ids.add(series_id)

    output_filename = 'yabancidizi_full.m3u'
    with open(output_filename, 'w', encoding='utf-8') as f:
        f.write(''.join(m3u_lines))
        
    content_count = len(m3u_lines) - 1
    if content_count > 0:
        print(f"\n'{output_filename}' dosyası başarıyla oluşturuldu! Toplam {content_count} içerik eklendi.", file=sys.stderr)
    else:
        print(f"\n'{output_filename}' dosyası oluşturuldu ancak içine eklenecek geçerli yayın bulunamadı.", file=sys.stderr)

if __name__ == "__main__":
    main()