import requests
import re
import sys
from typing import Dict, List, Optional, Set

# --- Konfigürasyon ---
# Kotlin dosyasından dinamik olarak alınacak, bu sadece bir geri dönüş adresi.
FALLBACK_BASE_URL = 'https://yabancidizi.so' 
# Dinamik URL'nin alınacağı yeni Kotlin dosyası
SOURCE_URL = 'https://raw.githubusercontent.com/fsamet/cs-Kekik/master/YabanciDizi/src/main/kotlin/com/nikyokki/YabanciDizi.kt'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    # Referer, embed sayfalarına erişim için önemli olabilir.
    'Referer': f'{FALLBACK_BASE_URL}/' 
}
# Öncelik verilecek player'ların sırası
PLAYER_PRIORITY = ["Mac", "Vidmoly"]

def get_dynamic_base_url() -> str:
    """Kotlin kaynağından dinamik olarak ana URL'yi çeker."""
    try:
        print("Dinamik ana URL GitHub'dan alınıyor...", file=sys.stderr)
        response = requests.get(SOURCE_URL, timeout=15)
        response.raise_for_status()
        content = response.text
        if match := re.search(r'override\s+var\s+mainUrl\s*=\s*"([^"]+)"', content):
            url = match.group(1).strip('/')
            print(f"Dinamik URL başarıyla bulundu: {url}", file=sys.stderr)
            HEADERS['Referer'] = f'{url}/' # Referer'ı da dinamik URL ile güncelle
            return url
    except requests.RequestException as e:
        print(f"GitHub'dan dinamik URL alınamadı: {e}", file=sys.stderr)
    
    print(f"Varsayılan URL kullanılıyor: {FALLBACK_BASE_URL}", file=sys.stderr)
    return FALLBACK_BASE_URL

def resolve_player_url(player: str, embed_url: str) -> Optional[str]:
    """
    Verilen gömme (embed) linkinden asıl .m3u8 video linkini çözer.
    Bu fonksiyon, YabanciDiziUtils.kt dosyasındaki mantığı taklit eder.
    """
    try:
        print(f"    -> '{player}' oynatıcısı çözümleniyor: {embed_url}", file=sys.stderr)
        page_content = requests.get(embed_url, headers=HEADERS, timeout=20).text

        if player == "Mac":
            # Kotlin kodundaki regex: "source:\s*'([^']+.m3u8)'"
            if match := re.search(r"source:\s*'([^']+\.m3u8)'", page_content):
                return match.group(1)
        
        elif player == "Vidmoly":
            # Kotlin kodundaki regex: "file:\s*\"([^\"]+)\""
            if match := re.search(r'file:\s*"([^"]+)"', page_content):
                return match.group(1)
        
        # Diğer player'lar için de benzer mantıklar buraya eklenebilir.
        # Okru, daha karmaşık bir yapıya sahip olduğu için şimdilik atlanmıştır.

    except requests.RequestException as e:
        print(f"      - Hata: '{player}' linki çözümlenemedi. {e}", file=sys.stderr)
    
    return None

def main():
    """Ana fonksiyon: M3U dosyasını oluşturur."""
    base_url = get_dynamic_base_url()
    m3u_lines = ["#EXTM3U\n"]
    processed_series_ids: Set[int] = set()

    print("Ana sayfadan diziler alınıyor...", file=sys.stderr)
    home_data = requests.get(f"{base_url}/api/home", headers=HEADERS, timeout=20).json()

    if not home_data:
        print("Ana sayfa verisi alınamadı. Betik sonlandırılıyor.", file=sys.stderr)
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
        
        series_detail_url = f"{base_url}/api/dizi/{series_id}"
        seasons_data = requests.get(series_detail_url, headers=HEADERS, timeout=20).json()

        if not isinstance(seasons_data, list):
            continue

        for season in seasons_data:
            episodes = season.get('episodes', [])
            season_num = season.get('season', 0)
            print(f"  - Sezon {season_num} için {len(episodes)} bölüm bulundu.", file=sys.stderr)

            for episode in episodes:
                sources = episode.get('sources', [])
                if not sources:
                    continue

                # Player'ları öncelik sırasına göre sırala
                sorted_sources = sorted(sources, key=lambda s: PLAYER_PRIORITY.index(s['player']) if s.get('player') in PLAYER_PRIORITY else len(PLAYER_PRIORITY))

                final_url = None
                for source in sorted_sources:
                    player = source.get('player')
                    embed_url = source.get('url')
                    if player and embed_url:
                        final_url = resolve_player_url(player, embed_url)
                        if final_url:
                            # Başarılı bir link bulununca döngüden çık
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