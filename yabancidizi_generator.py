import cloudscraper # requests yerine cloudscraper'ı import ediyoruz
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
PLAYER_PRIORITY = ["Mac", "Vidmoly"]

# Cloudscraper için bir oturum (scraper) oluşturuyoruz.
# Bu, tüm isteklerde aynı ayarları ve çerezleri kullanarak daha tutarlı çalışmasını sağlar.
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

def resolve_player_url(player: str, embed_url: str) -> Optional[str]:
    """Verilen gömme (embed) linkinden asıl .m3u8 video linkini çözer."""
    try:
        print(f"    -> '{player}' oynatıcısı çözümleniyor: {embed_url}", file=sys.stderr)
        # İstekleri artık scraper üzerinden yapıyoruz
        page_content = scraper.get(embed_url, headers=HEADERS, timeout=20).text

        if player == "Mac":
            if match := re.search(r"source:\s*'([^']+\.m3u8)'", page_content):
                return match.group(1)
        
        elif player == "Vidmoly":
            if match := re.search(r'file:\s*"([^"]+)"', page_content):
                return match.group(1)

    except Exception as e:
        print(f"      - Hata: '{player}' linki çözümlenemedi. {e}", file=sys.stderr)
    
    return None

def main():
    """Ana fonksiyon: M3U dosyasını oluşturur."""
    base_url = get_dynamic_base_url()
    m3u_lines = ["#EXTM3U\n"]
    processed_series_ids: Set[int] = set()

    print("Ana sayfadan diziler alınıyor...", file=sys.stderr)
    
    try:
        # Ana sayfa verisini de scraper ile çekiyoruz
        home_response = scraper.get(f"{base_url}/api/home", headers=HEADERS, timeout=30)
        home_response.raise_for_status()
        home_data = home_response.json() # JSON'a çevirme işlemi
    except Exception as e:
        # JSON hatası veya başka bir istek hatası olursa yakala
        print(f"Ana sayfa verisi alınamadı veya JSON formatında değil. Hata: {e}", file=sys.stderr)
        print(f"Alınan yanıt: {home_response.text[:200]}...", file=sys.stderr) # Yanıtın ilk 200 karakterini yazdır
        return

    all_series: List[Dict] = []
    for key in ['popular_series', 'latest_series', 'series']:
        if key in home_data and isinstance(home_data[key], list):
            all_series.extend(home_data[key])

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

        # ... (Geri kalan bölüm işleme mantığı aynı, bu yüzden değiştirilmedi) ...
        for season in seasons_data:
            episodes = season.get('episodes', [])
            season_num = season.get('season', 0)
            print(f"  - Sezon {season_num} için {len(episodes)} bölüm bulundu.", file=sys.stderr)

            for episode in episodes:
                sources = episode.get('sources', [])
                if not sources: continue

                sorted_sources = sorted(sources, key=lambda s: PLAYER_PRIORITY.index(s['player']) if s.get('player') in PLAYER_PRIORITY else len(PLAYER_PRIORITY))

                final_url = None
                for source in sorted_sources:
                    player, embed_url = source.get('player'), source.get('url')
                    if player and embed_url:
                        final_url = resolve_player_url(player, embed_url)
                        if final_url:
                            print(f"      + Başarılı: '{player}' kaynağından link alındı.", file=sys.stderr)
                            break 
                
                if final_url:
                    episode_title = episode.get('title', f"Bölüm {episode.get('episode')}")
                    series_poster = series_summary.get('poster', '')
                    group_title = f"{series_title} | Sezon {season_num}"
                    full_title = f"{series_title} - S{season_num:02d}E{episode.get('episode', 0):02d} - {episode_title}"
                    
                    m3u_lines.append(
                        f'#EXTINF:-1 tvg-id="{episode.get("id", "")}" tvg-name="{full_title}" '
                        f'tvg-logo="{series_poster}" group-title="{group_title}",{full_title}\n'
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