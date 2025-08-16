#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ATV.com.tr Scraper (Diziler ve Programlar) - NİHAİ SÜRÜM
Bu script, ATV'nin sunucu tarafı kontrollerini aşmak için önce ana sayfayı
ziyaret ederek bir oturum (session) başlatır ve ardından güvenilir API'ler
üzerinden tüm içerikleri çeker.

- ATV.m3u         -> Tüm içeriklerin birleşik listesi
- diziler/*.m3u   -> Her dizi için ayrı M3U dosyası
- programlar/*.m3u -> Her program için ayrı M3U dosyası
"""

import os
import sys
import time
import logging
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from requests.adapters import HTTPAdapter, Retry
from slugify import slugify

# ============================
# 1. TEMEL AYARLAR VE KONFİGÜRASYON
# ============================
BASE_DIR = Path(__file__).resolve().parent
ALL_M3U_DIR = str(BASE_DIR)
ALL_M3U_NAME = "ATV"
DIZILER_M3U_DIR = str(BASE_DIR / "diziler")
PROGRAMLAR_M3U_DIR = str(BASE_DIR / "programlar")

BASE_URL = "https://www.atv.com.tr/"
CONTENT_API_URL = "https://www.atv.com.tr/services/get-all-series-and-programs-by-category-slug"
STREAM_API_URL = "https://vms.atv.com.tr/vms/api/Player/GetVideoPlayer"

REQUEST_TIMEOUT = 30
REQUEST_PAUSE = 0.05
MAX_RETRIES = 5

# Tarayıcıyı taklit eden ve API'nin çalışması için gerekli olan başlıklar
DEFAULT_HEADERS = {
    "Referer": BASE_URL,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
}

# Hata ayıklama ve bilgilendirme için loglama ayarları
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("atv-scraper")

# Tekrar deneme mekanizmalı ve başlıkları ayarlanmış Session nesnesi
SESSION = requests.Session()
retries = Retry(total=MAX_RETRIES, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
SESSION.mount("https://", HTTPAdapter(max_retries=retries))
SESSION.headers.update(DEFAULT_HEADERS)


# ============================
# 2. M3U OLUŞTURMA YARDIMCI FONKSİYONLARI
# ============================
# Bu kısım önceki versiyonlarda doğru çalışıyordu, değişiklik yapılmadı.

def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def _atomic_write(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)

def _safe_series_filename(name: str) -> str:
    return slugify((name or "icerik").lower()) + ".m3u"

def create_m3us_for_category(channel_folder_path: str, data: List[Dict[str, Any]]) -> None:
    _ensure_dir(channel_folder_path)
    for item in (data or []):
        episodes = item.get("episodes") or []
        if not episodes: continue
        item_name = (item.get("name") or "Bilinmeyen").strip()
        item_logo = (item.get("img") or "").strip()
        plist_path = os.path.join(channel_folder_path, _safe_series_filename(item_name))
        lines = ["#EXTM3U"]
        for ep in episodes:
            stream = ep.get("stream_url")
            if not stream: continue
            ep_name = ep.get("name") or "Bölüm"
            group = item_name.replace('"', "'")
            lines.append(f'#EXTINF:-1 tvg-logo="{item_logo}" group-title="{group}",{ep_name}')
            lines.append(stream)
        if len(lines) > 1: _atomic_write(plist_path, "\n".join(lines) + "\n")

def create_single_m3u(channel_folder_path: str, data: List[Dict[str, Any]], custom_path: str) -> None:
    _ensure_dir(channel_folder_path)
    master_path = os.path.join(channel_folder_path, f"{custom_path}.m3u")
    lines = ["#EXTM3U"]
    for item in (data or []):
        item_name = (item.get("name") or "Bilinmeyen").strip()
        item_logo = (item.get("img") or "").strip()
        episodes = item.get("episodes") or []
        for ep in episodes:
            stream = ep.get("stream_url")
            if not stream: continue
            ep_name = ep.get("name") or "Bölüm"
            group = item_name.replace('"', "'")
            lines.append(f'#EXTINF:-1 tvg-logo="{item_logo}" group-title="{group}",{ep_name}')
            lines.append(stream)
    _atomic_write(master_path, "\n".join(lines) + "\n")


# ============================
# 3. VERİ ÇEKME FONKSİYONLARI (YENİ VE SAĞLAMLAŞTIRILMIŞ)
# ============================

def initialize_session() -> bool:
    """
    KRİTİK ADIM: Ana sayfayı ziyaret ederek sunucudan gerekli session cookie'lerini alır.
    Bu olmadan API istekleri başarısız olur.
    """
    try:
        log.info("Oturum başlatılıyor ve cookie'ler alınıyor...")
        response = SESSION.get(BASE_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        if response.cookies:
            log.info("Oturum başarıyla başlatıldı.")
            return True
        log.warning("Oturum başlatıldı ancak sunucudan cookie alınamadı.")
        return False
    except requests.exceptions.RequestException as e:
        log.error("Ana sayfa ziyareti başarısız! Oturum başlatılamadı. Hata: %s", e)
        return False

def get_content_list_from_api(slug: str, content_type: str) -> List[Dict[str, str]]:
    """ATV'nin resmi API'sini kullanarak dizi/program listesini çeker."""
    log.info("API'den '%s' listesi çekiliyor...", content_type)
    try:
        response = SESSION.get(CONTENT_API_URL, params={"slug": slug}, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        api_data = response.json()

        if not isinstance(api_data, list):
            log.error("API'den beklenen liste formatında veri gelmedi. Gelen veri: %s", str(api_data)[:100])
            return []

        content_list = [
            {
                "name": item.get("Name", "İsimsiz").strip(),
                "url": urljoin(BASE_URL, item.get("Url", "")),
                "img": urljoin(BASE_URL, item.get("ImageUrl", "")),
                "type": content_type
            }
            for item in api_data
        ]
        log.info("-> Başarılı: %d adet %s bulundu.", len(content_list), content_type)
        return content_list
    except (requests.exceptions.RequestException, ValueError) as e:
        log.error("API'den '%s' listesi alınırken kritik hata: %s", content_type, e)
        return []

def get_episodes_for_content(content_url: str) -> List[Dict[str, str]]:
    """Bir içeriğin 'bölümler' sayfasını analiz ederek bölüm listesini alır."""
    episodes_url = urljoin(content_url.rstrip('/') + "/", "bolumler")
    try:
        response = SESSION.get(episodes_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        items = soup.select("article.widget-item a")
        if not items:
            log.warning("-> Bölüm sayfasında 'article.widget-item a' seçicisiyle eşleşen bölüm bulunamadı: %s", episodes_url)
            return []
        
        return [
            {
                "name": a_tag.select_one("div.name").get_text(strip=True),
                "url": urljoin(BASE_URL, a_tag["href"]),
            }
            for a_tag in items if a_tag.get("href") and a_tag.select_one("div.name")
        ]
    except requests.exceptions.RequestException as e:
        log.warning("-> Bölüm listesi sayfası alınamadı (%s): %s", episodes_url, e)
        return []

def get_stream_url(episode_url: str) -> Optional[str]:
    """Bölüm sayfasından video ID'sini alıp VMS API'sinden yayın URL'sini çeker."""
    try:
        response = SESSION.get(episode_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        video_container = soup.find("div", {"id": "video-container", "data-videoid": True})
        if not video_container:
            log.warning("--> Video ID bulunamadı: %s", episode_url)
            return None
        
        video_id = video_container["data-videoid"]
        vms_response = SESSION.get(STREAM_API_URL, params={"id": video_id}, timeout=REQUEST_TIMEOUT)
        vms_response.raise_for_status()
        return vms_response.json()["data"]["video"]["url"]
    except (requests.exceptions.RequestException, KeyError, ValueError) as e:
        log.warning("--> Yayın URL'si alınamadı (%s): %s", episode_url, e)
        return None


# ============================
# 4. ANA İŞLEM AKIŞI
# ============================
def run() -> None:
    # 1. Adım: Her şeyden önce oturumu başlat. Başarısız olursa devam etme.
    if not initialize_session():
        log.critical("Oturum başlatılamadığı için işlem durduruldu. Lütfen internet bağlantınızı veya site erişimini kontrol edin.")
        return

    # 2. Adım: API'yi kullanarak tüm dizileri ve programları çek.
    diziler = get_content_list_from_api("diziler", "dizi")
    programlar = get_content_list_from_api("programlar", "program")
    
    all_content = diziler + programlar
    if not all_content:
        log.error("Hiçbir dizi veya program bulunamadı. API yanıt vermiyor veya boş veri döndürdü. İşlem durduruldu.")
        return
        
    log.info("Toplam %d içerik bulundu. Bölümler ve yayın linkleri çekilecek...", len(all_content))
    processed_data: List[Dict[str, Any]] = []

    # 3. Adım: Her bir içerik için bölümleri ve her bölüm için yayın linkini çek.
    for content in tqdm(all_content, desc="Tüm İçerikler"):
        log.info("İşleniyor: %s (%s)", content["name"], content["type"].upper())
        episodes = get_episodes_for_content(content["url"])
        if not episodes:
            log.warning("-> '%s' için bölüm bulunamadı, atlanıyor.", content["name"])
            continue

        temp_content = dict(content)
        temp_content["episodes"] = []

        for ep in tqdm(episodes, desc=f"  -> {content['name']}", leave=False):
            stream_url = get_stream_url(ep["url"])
            if stream_url:
                temp_episode = dict(ep)
                temp_episode["stream_url"] = stream_url
                temp_content["episodes"].append(temp_episode)
            time.sleep(REQUEST_PAUSE) # Sunucuyu yormamak için küçük bir bekleme

        if temp_content["episodes"]:
            processed_data.append(temp_content)

    # 4. Adım: Çekilen tüm verileri M3U dosyalarına yaz.
    if not processed_data:
        log.error("Tüm içerikler işlendi ancak hiçbir bölüm için geçerli yayın linki bulunamadı. M3U dosyaları oluşturulmayacak.")
        return

    log.info("Veri çekme tamamlandı. M3U dosyaları oluşturuluyor...")
    try:
        diziler_data = [item for item in processed_data if item.get("type") == "dizi"]
        programlar_data = [item for item in processed_data if item.get("type") == "program"]

        if diziler_data: create_m3us_for_category(DIZILER_M3U_DIR, diziler_data)
        if programlar_data: create_m3us_for_category(PROGRAMLAR_M3U_DIR, programlar_data)
        create_single_m3u(ALL_M3U_DIR, processed_data, ALL_M3U_NAME)
        log.info("TÜM İŞLEMLER BAŞARIYLA TAMAMLANDI!")
    except Exception as e:
        log.critical("M3U dosyaları oluşturulurken beklenmedik bir hata oluştu: %s", e, exc_info=True)


if __name__ == "__main__":
    run()