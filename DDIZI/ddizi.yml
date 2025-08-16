#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
DDIZI.im Scraper - GÜVENİLİR VE ÇALIŞAN SÜRÜM
Bu script, ddizi.im sitesindeki tüm dizileri, bölümleri ve yayın linklerini
çekerek M3U listeleri oluşturur.

- DDIZI.m3u         -> Tüm dizilerin birleşik listesi
- diziler/*.m3u   -> Her dizi için ayrı M3U dosyası
"""

import os
import re
import sys
import time
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from slugify import slugify
from requests.adapters import HTTPAdapter, Retry

# ============================
# 1. TEMEL AYARLAR VE SABİTLER
# ============================
BASE_DIR = Path(__file__).resolve().parent
ALL_M3U_DIR = str(BASE_DIR)
ALL_M3U_NAME = "DDIZI"
SERIES_M3U_DIR = str(BASE_DIR / "diziler")

BASE_URL = "https://www.ddizi.im/"
SERIES_LIST_URL = urljoin(BASE_URL, "dizi-listesi")

REQUEST_TIMEOUT = 30
MAX_RETRIES = 5

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": BASE_URL,
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("ddizi-scraper")

SESSION = requests.Session()
retries = Retry(total=MAX_RETRIES, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
SESSION.mount("https://", HTTPAdapter(max_retries=retries))
SESSION.headers.update(DEFAULT_HEADERS)

# ============================
# 2. M3U OLUŞTURMA YARDIMCILARI (DEĞİŞİKLİK YOK)
# ============================
def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def _atomic_write(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)

def _safe_series_filename(name: str) -> str:
    return slugify((name or "dizi").lower()) + ".m3u"

def create_m3us_for_series(channel_folder_path: str, data: List[Dict[str, Any]]) -> None:
    _ensure_dir(channel_folder_path)
    for series in data:
        episodes = series.get("episodes") or []
        if not episodes: continue
        series_name = series.get("name", "Bilinmeyen").strip()
        series_logo = series.get("img", "").strip()
        plist_path = os.path.join(channel_folder_path, _safe_series_filename(series_name))
        lines = ["#EXTM3U"]
        for ep in episodes:
            stream = ep.get("stream_url")
            if not stream: continue
            ep_name = ep.get("name", "Bölüm")
            group = series_name.replace('"', "'")
            lines.append(f'#EXTINF:-1 tvg-logo="{series_logo}" group-title="{group}",{ep_name}')
            lines.append(stream)
        if len(lines) > 1: _atomic_write(plist_path, "\n".join(lines) + "\n")

def create_single_m3u(channel_folder_path: str, data: List[Dict[str, Any]], custom_path: str) -> None:
    _ensure_dir(channel_folder_path)
    master_path = os.path.join(channel_folder_path, f"{custom_path}.m3u")
    lines = ["#EXTM3U"]
    for series in data:
        series_name = series.get("name", "Bilinmeyen").strip()
        series_logo = series.get("img", "").strip()
        episodes = series.get("episodes", [])
        for ep in episodes:
            stream = ep.get("stream_url")
            if not stream: continue
            ep_name = ep.get("name", "Bölüm")
            group = series_name.replace('"', "'")
            lines.append(f'#EXTINF:-1 tvg-logo="{series_logo}" group-title="{group}",{ep_name}')
            lines.append(stream)
    _atomic_write(master_path, "\n".join(lines) + "\n")

# ============================
# 3. VERİ ÇEKME FONKSİYONLARI (DDIZI.IM İÇİN ÖZEL)
# ============================

def get_all_series() -> List[Dict[str, str]]:
    """Sitedeki tüm dizilerin listesini çeker."""
    log.info("Sitedeki tüm dizi listesi alınıyor...")
    try:
        response = SESSION.get(SERIES_LIST_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        
        series_list = []
        links = soup.select("ul.dizi-list li a")
        for link in links:
            if link.get("href"):
                series_list.append({
                    "name": link.text.strip(),
                    "url": urljoin(BASE_URL, link["href"])
                })
        log.info("-> Başarılı: %d adet dizi bulundu.", len(series_list))
        return series_list
    except requests.RequestException as e:
        log.critical("Dizi listesi alınamadı, işlem durduruldu: %s", e)
        return []

def get_episodes_for_series(series_url: str) -> Tuple[str, List[Dict[str, str]]]:
    """Bir dizinin tüm bölümlerini ve posterini çeker."""
    episodes = []
    poster_img = ""
    try:
        response = SESSION.get(series_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        
        # Posteri al
        poster_tag = soup.select_one("div.dizi-poster img")
        if poster_tag:
            poster_img = urljoin(BASE_URL, poster_tag.get("src", ""))

        # Bölümleri al
        episode_links = soup.select("div.sezon-bolumleri ul li a")
        for link in episode_links:
            if link.get("href"):
                episodes.append({
                    "name": link.text.strip(),
                    "url": urljoin(BASE_URL, link["href"])
                })
        return poster_img, episodes
    except requests.RequestException as e:
        log.error("-> '%s' için bölümler alınamadı: %s", series_url, e)
        return poster_img, []

def get_stream_url_from_episode(episode_url: str) -> Optional[str]:
    """Bölüm sayfasından video yayın linkini (m3u8) çeker."""
    try:
        # 1. Adım: Bölüm sayfasını al ve Fembed iframe'ini bul
        response = SESSION.get(episode_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        
        iframe = soup.find("iframe", {"src": re.compile(r"//(femax20|supervideo)\.com")})
        if not iframe:
            log.warning("--> Fembed/Supervideo iframe'i bulunamadı.")
            return None
        
        fembed_url = "https:" + iframe["src"]
        video_id = fembed_url.split('/')[-1]
        
        # 2. Adım: Fembed API'sine istek at
        fembed_api_url = f"https://femax20.com/api/source/{video_id}"
        api_response = SESSION.post(fembed_api_url, headers={"Referer": fembed_url}, timeout=REQUEST_TIMEOUT)
        api_response.raise_for_status()
        
        api_data = api_response.json()
        if api_data.get("success") and api_data.get("data"):
            # En yüksek kaliteli m3u8 linkini seç
            highest_quality_source = api_data["data"][-1]
            return highest_quality_source.get("file")
            
        log.warning("--> Fembed API'sinden geçerli veri alınamadı.")
        return None
    except requests.RequestException as e:
        log.warning("--> Yayın linki alınırken hata: %s", e)
        return None
    except Exception as e:
        log.error("--> Yayın linki işlenirken beklenmedik hata: %s", e)
        return None

# ============================
# 4. ANA İŞLEM AKIŞI
# ============================
def run() -> None:
    series_list = get_all_series()
    if not series_list:
        return
        
    log.info("Tüm diziler için bölümler ve yayın linkleri çekilecek...")
    processed_data = []

    for series in tqdm(series_list, desc="Tüm Diziler"):
        log.info("İşleniyor: %s", series["name"])
        poster_img, episodes = get_episodes_for_series(series["url"])
        
        if not episodes:
            log.warning("-> '%s' için bölüm bulunamadı, atlanıyor.", series["name"])
            continue

        temp_series = dict(series)
        temp_series["img"] = poster_img
        temp_series["episodes"] = []

        for ep in tqdm(episodes, desc=f"  -> {series['name']}", leave=False):
            stream_url = get_stream_url_from_episode(ep["url"])
            if stream_url:
                ep_with_stream = dict(ep)
                ep_with_stream["stream_url"] = stream_url
                temp_series["episodes"].append(ep_with_stream)
            time.sleep(0.1) # Sunucuyu yormamak için küçük bekleme

        if temp_series["episodes"]:
            processed_data.append(temp_series)

    if not processed_data:
        log.error("Hiçbir bölüm için geçerli yayın linki bulunamadı. M3U dosyaları oluşturulmayacak.")
        return

    log.info("Veri çekme tamamlandı. M3U dosyaları oluşturuluyor...")
    try:
        create_m3us_for_series(SERIES_M3U_DIR, processed_data)
        create_single_m3u(ALL_M3U_DIR, processed_data, ALL_M3U_NAME)
        log.info("TÜM İŞLEMLER BAŞARIYLA TAMAMLANDI!")
    except Exception as e:
        log.critical("M3U dosyaları oluşturulurken hata: %s", e, exc_info=True)


if __name__ == "__main__":
    run()
