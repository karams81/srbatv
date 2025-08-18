import os
import requests
import concurrent.futures

# --- LİG BİLGİLERİ ---

# Trendyol Süper Lig için veri yapıları
super_lig_sezonlar = {
    32: '2010/2011', 
    30: '2011/2012',
    25: '2012/2013',
    34: '2013/2014',
    37: '2014/2015',
    24: '2015/2016',
    29: '2016/2017',
    23: '2017/2018',
    20: '2018/2019',
    994: '2019/2020',
    3189: '2020/2021',
    3308: '2021/2022',
    3438: '2022/2023',
    3580: '2023/2024',
    3746: '2024/2025',
    3853: '2025/2026', 
}

super_lig_haftalar = {
    32: range(1, 35), 30: range(1, 35), 25: range(1, 35),
    34: range(1, 35), 37: range(1, 35), 24: range(1, 35),
    29: range(1, 35), 23: range(1, 35), 20: range(1, 35),
    994: range(1, 35), 3189: range(1, 43), 3308: range(1, 39),
    3438: range(1, 39), 3580: range(1, 39), 3746: range(1, 39),
    3853: range(1, 39),
}

super_lig_st = {
    30: 2899,
}

# Trendyol 1. Lig için veri yapıları
birinci_lig_sezonlar = {
    1108: '2017/2018',
    1105: '2018/2019',
    908: '2019/2020',
    1034: '2019/2020 Ekstra', # Aynı sezonda farklı ID olabilir
    3190: '2020/2021',
    3309: '2021/2022',
    3440: '2022/2023',
    3583: '2023/2024',
    3759: '2024/2025',
    3856: '2025/2026',
}

# 1. Lig için hafta aralıkları (1'den belirtilen haftaya kadar)
birinci_lig_haftalar = {
    1108: range(1, 35),  # 34 Hafta
    1105: range(1, 35),  # 34 Hafta
    908:  range(1, 35),  # 34 Hafta
    1034: range(1, 38),  # 37 Hafta
    3190: range(1, 38),  # 37 Hafta
    3309: range(1, 41),  # 40 Hafta
    3440: range(1, 42),  # 41 Hafta
    3583: range(1, 38),  # 37 Hafta
    3759: range(1, 43),  # 42 Hafta
    3856: range(1, 3),   # 2 Hafta (mevcut veri)
}

# 1. Lig için st kodları
birinci_lig_st = {
    1108: 5067,
    1105: 5166,
    908:  517,
    1034: 0,
    3190: 0,
    3309: 56523,
    3440: 57092,
    3583: 58256,
    3759: 58686,
    3856: 0,
}


# --- ANA KOD ---

# Çıktı klasörünü oluştur
output_folder = 'playsport'
os.makedirs(output_folder, exist_ok=True)

def fetch_and_parse(url_info):
    """
    Verilen URL'den veriyi çeker, M3U formatına dönüştürür.
    """
    url, group_title = url_info
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # HTTP hatalarını kontrol et
        data = response.json()
        events = data.get('Data', {}).get('events', [])
        result = []
        for event in events:
            home = event.get('homeTeam', {}).get('name', 'Ev Sahibi')
            home_score = event.get('homeTeam', {}).get('matchScore', '-')
            away = event.get('awayTeam', {}).get('name', 'Deplasman')
            away_score = event.get('awayTeam', {}).get('matchScore', '-')
            video_url = event.get('highlightVideoUrl')
            logo = event.get('highlightThumbnail', '')
            match_id = event.get('matchId', '')

            if video_url:
                title = f"{home} {home_score}-{away_score} {away}"
                line1 = f'#EXTINF:-1 tvg-id="{match_id}" tvg-logo="{logo}" group-title="{group_title}",{title}\n'
                line2 = f"{video_url}\n"
                result.append((group_title, line1, line2))
        return result
    except requests.exceptions.RequestException as e:
        print(f"URL alınırken hata oluştu: {url} - Hata: {e}")
        return []
    except Exception as e:
        print(f"Veri işlenirken bir hata oluştu: {url} - Hata: {e}")
        return []

# Tüm liglerden çekilecek URL'lerin listesi
all_urls_to_fetch = []

# Süper Lig URL'lerini oluştur
for sezon_id, sezon_adi in super_lig_sezonlar.items():
    haftalar = super_lig_haftalar.get(sezon_id, range(1, 39)) # Varsayılan hafta aralığı
    st = super_lig_st.get(sezon_id, 0) # Varsayılan st değeri
    group_title = f"Süper Lig {sezon_adi}"
    for hafta in haftalar:
        url = f"https://beinsports.com.tr/api/highlights/events?sp=1&o=18&s={sezon_id}&r={hafta}&st={st}"
        all_urls_to_fetch.append((url, group_title))

# Trendyol 1. Lig URL'lerini oluştur
for sezon_id, sezon_adi in birinci_lig_sezonlar.items():
    haftalar = birinci_lig_haftalar.get(sezon_id, range(1, 2)) # ID bulunamazsa varsayılan olarak 1 hafta
    st = birinci_lig_st.get(sezon_id, 0) # Varsayılan st değeri
    group_title = f"Trendyol 1. Lig {sezon_adi}"
    for hafta in haftalar:
        url = f"https://beinsports.com.tr/api/highlights/events?sp=1&o=130&s={sezon_id}&r={hafta}&st={st}"
        all_urls_to_fetch.append((url, group_title))


# Sonuçları gruplamak için sözlük
grouped_results = {}

# Eşzamanlı olarak tüm URL'leri çek ve işle
with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
    # `map` fonksiyonu, `fetch_and_parse` fonksiyonunu `all_urls_to_fetch` listesindeki her bir eleman için çalıştırır.
    future_results = executor.map(fetch_and_parse, all_urls_to_fetch)
    
    # Gelen sonuçları işle
    for result_list in future_results:
        for group_title, line1, line2 in result_list:
            if group_title not in grouped_results:
                grouped_results[group_title] = []
            grouped_results[group_title].append((line1, line2))

# Tüm sezon/lig kombinasyonlarını tek bir dosyada toplamak için liste
all_lines_combined = []

# Gruplanmış sonuçları dosyalara yaz
for group_title, lines in sorted(grouped_results.items()):
    # Dosya ve klasör adları için geçersiz karakterleri temizle
    safe_folder_name = group_title.replace('/', '-').replace(' ', '_')
    folder_path = os.path.join(output_folder, safe_folder_name)
    os.makedirs(folder_path, exist_ok=True)
    
    file_path = os.path.join(folder_path, f"{safe_folder_name}.m3u")
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n\n")
        for line1, line2 in lines:
            f.write(line1)
            f.write(line2)
            all_lines_combined.append((line1, line2))

# Tüm lig ve sezonları içeren tek bir M3U dosyası oluştur
all_m3u_path = os.path.join(output_folder, 'all_leagues.m3u')
with open(all_m3u_path, 'w', encoding='utf-8') as f:
    f.write("#EXTM3U\n\n")
    # Önce gruplara göre sıralanmış sonuçları yaz
    for line1, line2 in all_lines_combined:
        f.write(line1)
        f.write(line2)

print(f"'{output_folder}' klasörü içinde her lig/sezon için klasörler, M3U dosyaları ve 'all_leagues.m3u' başarıyla oluşturuldu.")

# Sakultah tarafından yapılmıştır iyi kullanımlar :)