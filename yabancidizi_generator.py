import cloudscraper
import re
import sys
from bs4 import BeautifulSoup
from typing import Dict, List, Optional, Set

# --- Konfigürasyon ---
FALLBACK_BASE_URL = 'https://yabancidizi.so' 
SOURCE_URL = 'https://raw.githubusercontent.com/fsamet/cs-Kekik/master/YabanciDizi/src/main/kotlin/com/nikyokki/YabanciDizi.kt'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': f'{FALLBACK_BASE_URL}/',
    'X-Requested-With': 'XMLHttpRequest' # AJAX isteği için bu başlık önemli
}
MAX_PAGES_TO_SCAN = 20 # Kaç sayfayı kontrol edeceğimiz

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

def get_vidmoly_embed_url(base_url: str, episode_url: str) -> Optional[str]:
    """
    Bölüm sayfasından Vidmoly 'data-id'sini alıp AJAX isteği ile embed linkini çözer.
    """
    try:
        # 1. Bölüm sayfasının HTML'ini al
        episode_page_res = scraper.get(episode_url, headers=HEADERS, timeout=20)
        episode_page_res.raise_for_status()
        soup = BeautifulSoup(episode_page_res.text, 'html.parser')

        # 2. Vidmoly oynatıcı butonunu bul
        vidmoly_button = soup.find('a', text='Vidmoly')
        if not vidmoly_button or not vidmoly_button.has_attr('data-id'):
            return None
        
        data_id = vidmoly_button['data-id']
        
        # 3. AJAX POST isteğini yap
        ajax_url = f"{base_url}/wp-admin/admin-ajax.php"
        payload = {
            "action": "get_player_embed",
            "id": data_id
        }
        ajax_res = scraper.post(ajax_url, headers=HEADERS, data=payload, timeout=20)
        ajax_res.raise_for_status()
        
        # 4. Gelen cevaptaki iframe'in src'sini al
        iframe_soup = BeautifulSoup(ajax_res.text, 'html.parser')
        iframe = iframe_soup.find('iframe')
        
        return iframe['src'] if iframe and iframe.has_attr('src') else None

    except Exception as e:
        print(f"  - Vidmoly linki alınırken hata: {e}", file=sys.stderr)
        return None

def main():
    base_url = get_dynamic_base_url()
    m3u_lines = ["#EXTM3U\n"]
    
    print("Diziler HTML sayfaları taranarak bulunuyor...", file=sys.stderr)
    
    for page in range(1, MAX_PAGES_TO_SCAN + 1):
        try:
            page_url = f"{base_url}/diziler/sayfa/{page}"
            print(f"\nSayfa {page} taranıyor: {page_url}", file=sys.stderr)
            
            main_page_res = scraper.get(page_url, headers=HEADERS, timeout=20)
            main_page_res.raise_for_status()
            soup = BeautifulSoup(main_page_res.text, 'html.parser')
            
            series_list = soup.select("div.poster-card a")
            if not series_list:
                print(f"Sayfa {page} üzerinde dizi bulunamadı. Tarama tamamlandı.", file=sys.stderr)
                break

            for series_link in series_list:
                series_url = series_link['href']
                series_title = series_link.find('h3').text.strip() if series_link.find('h3') else "Bilinmeyen Dizi"
                series_poster = series_link.find('img')['src'] if series_link.find('img') and series_link.find('img').has_attr('src') else ""
                
                print(f"-> Dizi işleniyor: {series_title}", file=sys.stderr)
                
                series_page_res = scraper.get(series_url, headers=HEADERS, timeout=20)
                series_soup = BeautifulSoup(series_page_res.text, 'html.parser')
                
                seasons = series_soup.select("div.seasons-list > div")
                for season_div in seasons:
                    season_title = season_div.find('h3').text.strip() if season_div.find('h3') else ""
                    season_num_match = re.search(r'(\d+)\.\s*Sezon', season_title)
                    season_num = int(season_num_match.group(1)) if season_num_match else 0

                    episodes = season_div.select("div.season-episodes > a")
                    for episode_link in episodes:
                        episode_url = episode_link['href']
                        episode_title = episode_link.text.strip()
                        episode_num_match = re.search(r'(\d+)\.\s*Bölüm', episode_title)
                        episode_num = int(episode_num_match.group(1)) if episode_num_match else 0
                        
                        vidmoly_url = get_vidmoly_embed_url(base_url, episode_url)
                        
                        if vidmoly_url:
                            print(f"  + Link bulundu: {series_title} S{season_num:02d}E{episode_num:02d}", file=sys.stderr)
                            group_title = f"{series_title} | Sezon {season_num}"
                            full_title = f"{series_title} - S{season_num:02d}E{episode_num:02d} - {episode_title}"
                            m3u_lines.append(
                                f'#EXTINF:-1 tvg-name="{full_title}" tvg-logo="{series_poster}" group-title="{group_title}",{full_title}\n'
                                f'{vidmoly_url}\n'
                            )

        except Exception as e:
            print(f"Sayfa {page} işlenirken bir hata oluştu: {e}", file=sys.stderr)
            continue

    output_filename = 'yabancidizi_full.m3u'
    with open(output_filename, 'w', encoding='utf-8') as f:
        f.write(''.join(m3u_lines))
        
    content_count = len(m3u_lines) - 1
    print(f"\nİşlem tamamlandı. '{output_filename}' dosyasına {content_count} içerik eklendi.", file=sys.stderr)

if __name__ == "__main__":
    main()