#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ATV.com.tr Scraper (Diziler ve Programlar) - API TABANLI KESİN ÇÖZÜM
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
# ÇIKTI KONUMLARI
# ============================
BASE_DIR = Path(__file__).resolve().parent
ALL_M3U_DIR = str(BASE_DIR)
ALL_M3U_NAME = "ATV"
DIZILER_M3U_DIR = str(BASE_DIR / "diziler")
PROGRAMLAR_M3U_DIR = str(BASE_DIR / "programlar")

# ============================
# API ve SABİTLER
# ============================
BASE_URL = "https://www.atv.com.tr/"
# İÇERİK LİSTESİNİ ÇEKEN GİZLİ API ENDPOINT'İ
CONTENT_API_URL = "https://www.atv.com.tr/services/get-all-series-and-programs-by-category-slug"
# VİDEO YAYIN LİNKİNİ VEREN API ENDPOINT'İ
STREAM_API_URL = "https://vms.atv.com.tr/vms/api/Player/GetVideoPlayer"

REQUEST_TIMEOUT = 30
REQUEST_PAUSE = 0.05
BACKOFF_FACTOR = 0.5
MAX_RETRIES = 5

DEFAULT_HEADERS = {
    "Referer": BASE_URL,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest", # API'nin çalışması için bu header önemli
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("atv-scraper")

SESSION = requests.Session()
retries = Retry(total=MAX_RETRIES, backoff_factor=BACKOFF_FACTOR, status_forcelist=(429, 500, 502, 503, 504))
SESSION.mount("https://", HTTPAdapter(max_retries=retries))
SESSION.headers.update(DEFAULT_HEADERS)

# ============================
# M3U YARDIMCILARI (Değişiklik Gerekmiyor)
# ============================

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
# GÜNCELLENMİŞ ÇEKİRDEK FONKSİYONLAR
# ============================

def get_content_list_from_api(slug: str, content_type: str) -> List[Dict[str, str]]:
    """
    DEĞİŞİKLİK: HTML yerine doğrudan ATV'nin gizli API'sine istek atarak
    dizi/program listesini JSON olarak çeker. Bu yöntem çok daha hızlı ve güvenilirdir.
    """
    log.info("%s listesi API'den alınıyor...", content_type.capitalize())
    content_list: List[Dict[str, str]] = []
    try:
        r = SESSION.get(CONTENT_API_URL, params={"slug": slug}, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        api_data = r.json()

        for item in api_data:
            content_list.append({
                "name": item.get("Name", "İsimsiz").strip(),
                "url": urljoin(BASE_URL, item.get("Url", "")),
                "img": urljoin(BASE_URL, item.get("ImageUrl", "")),
                "type": content_type
            })
        log.info("%d adet %s bulundu.", len(content_list), content_type)
        return content_list
    except Exception as e:
        log.error("API'den %s listesi alınırken hata oluştu: %s", content_type, e)
        return []

def get_episodes_for_content(content_url: str) -> List[Dict[str, str]]:
    """Bir içeriğin 'bölümler' sayfasını kazıyarak (scrape) bölüm listesini alır."""
    episodes_url = urljoin(content_url.rstrip('/') + "/", "bolumler")
    all_episodes: List[Dict[str, str]] = []
    try:
        r = SESSION.get(episodes_url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        items = soup.select("article.widget-item a") # Bölüm listesi HTML'de mevcut
        for a_tag in items:
            name_div = a_tag.select_one("div.name")
            if not (a_tag.get("href") and name_div): continue
            all_episodes.append({
                "name": name_div.get_text(strip=True),
                "url": urljoin(BASE_URL, a_tag["href"]),
            })
        return all_episodes
    except Exception as e:
        log.warning("%s için bölüm listesi alınamadı: %s", content_url, e)
        return []

def get_stream_url(episode_url: str) -> Optional[str]:
    """Bölüm sayfasından video ID'sini alıp VMS API'sinden stream URL'sini çeker."""
    try:
        r = SESSION.get(episode_url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        video_container = soup.find("div", {"id": "video-container", "data-videoid": True})
        if not video_container:
            log.warning("Video ID bulunamadı: %s", episode_url)
            return None
        
        video_id = video_container["data-videoid"]
        r_vms = SESSION.get(STREAM_API_URL, params={"id": video_id}, timeout=REQUEST_TIMEOUT)
        r_vms.raise_for_status()
        return r_vms.json()["data"]["video"]["url"]
    except Exception as e:
        log.warning("Stream URL alınamadı (%s): %s", episode_url, e)
        return None

# ============================
# ANA İŞLEM AKIŞI
# ============================
def run(start: int = 0, end: int = 0) -> List[Dict[str, Any]]:
    diziler = get_content_list_from_api("diziler", "dizi")
    programlar = get_content_list_from_api("programlar", "program")
    
    all_content = diziler + programlar
    log.info("Toplam %d içerik (dizi/program) bulundu. İşleme başlanıyor.", len(all_content))

    if not all_content: return []

    output: List[Dict[str, Any]] = []
    end_index = len(all_content) if end == 0 else min(end, len(all_content))
    start_index = max(0, start)

    for i in tqdm(range(start_index, end_index), desc="İçerikler"):
        content = all_content[i]
        log.info("[%d/%d] %s (%s)", i + 1, end_index, content["name"], content["type"].upper())

        episodes = get_episodes_for_content(content["url"])
        if not episodes:
            log.warning("-> Bölüm bulunamadı: %s", content["name"])
            continue

        temp_content = dict(content)
        temp_content["episodes"] = []

        for ep in tqdm(episodes, desc="   Bölümler", leave=False):
            time.sleep(REQUEST_PAUSE) # Her bölüm arasında çok kısa bekle
            stream_url = get_stream_url(ep["url"])
            if stream_url:
                temp_episode = dict(ep)
                temp_episode["stream_url"] = stream_url
                temp_content["episodes"].append(temp_episode)

        if temp_content["episodes"]:
            output.append(temp_content)

    return output

def save_outputs(data: List[Dict[str, Any]]) -> None:
    if not data:
        log.warning("Kaydedilecek veri bulunamadı. M3U oluşturulmadı.")
        return
    try:
        diziler_data = [item for item in data if item.get("type") == "dizi"]
        programlar_data = [item for item in data if item.get("type") == "program"]

        if diziler_data:
            create_m3us_for_category(DIZILER_M3U_DIR, diziler_data)
            log.info("Dizi M3U dosyaları '%s' klasörüne oluşturuldu.", DIZILER_M3U_DIR)
        
        if programlar_data:
            create_m3us_for_category(PROGRAMLAR_M3U_DIR, programlar_data)
            log.info("Program M3U dosyaları '%s' klasörüne oluşturuldu.", PROGRAMLAR_M3U_DIR)

        create_single_m3u(ALL_M3U_DIR, data, ALL_M3U_NAME)
        log.info("Birleşik M3U dosyası (%s.m3u) oluşturuldu.", ALL_M3U_NAME)
    except Exception as e:
        log.error("M3U oluşturma sırasında kritik hata: %s", e, exc_info=True)

def parse_args(argv: List[str]) -> Tuple[int, int]:
    start, end = 0, 0
    if len(argv) >= 2:
        try: end = int(argv[1])
        except Exception: pass
    if len(argv) >= 3:
        try:
            start = int(argv[1])
            end = int(argv[2])
        except Exception: pass
    return start, end

def main():
    start, end = parse_args(sys.argv)
    data = run(start=start, end=end)
    save_outputs(data)

if __name__ == "__main__":
    main()