#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ATV.com.tr Scraper (Diziler ve Programlar) - KESİN ÇÖZÜM
- ATV.m3u         -> Tüm içeriklerin birleşik listesi
- diziler/*.m3u   -> Her dizi için ayrı M3U dosyası
- programlar/*.m3u -> Her program için ayrı M3U dosyası

Kullanım:
  python atv.py
  python atv.py 10       (ilk 10 içeriği alır - dizi/program karışık)
  python atv.py 5 15     (5. içerikten 15. içeriğe kadar alır)
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

# Tek dosyalık birleşik liste: ./ATV.m3u
ALL_M3U_DIR = str(BASE_DIR)
ALL_M3U_NAME = "ATV"

# Kategori bazlı listeler için klasörler
DIZILER_M3U_DIR = str(BASE_DIR / "diziler")
PROGRAMLAR_M3U_DIR = str(BASE_DIR / "programlar")

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
        if not episodes:
            continue

        item_name = (item.get("name") or "Bilinmeyen İçerik").strip()
        item_logo = (item.get("img") or "").strip()
        plist_name = _safe_series_filename(item_name)
        plist_path = os.path.join(channel_folder_path, plist_name)

        lines: List[str] = ["#EXTM3U"]
        for ep in episodes:
            stream = ep.get("stream_url")
            if not stream:
                continue
            ep_name = ep.get("name") or "Bölüm"
            logo_for_line = item_logo or ep.get("img") or ""
            group = item_name.replace('"', "'")
            lines.append(f'#EXTINF:-1 tvg-logo="{logo_for_line}" group-title="{group}",{ep_name}')
            lines.append(stream)

        if len(lines) > 1:
            _atomic_write(plist_path, "\n".join(lines) + "\n")

def create_single_m3u(channel_folder_path: str, data: List[Dict[str, Any]], custom_path: str) -> None:
    _ensure_dir(channel_folder_path)
    master_path = os.path.join(channel_folder_path, f"{custom_path}.m3u")
    lines: List[str] = ["#EXTM3U"]
    for item in (data or []):
        item_name = (item.get("name") or "Bilinmeyen İçerik").strip()
        item_logo = (item.get("img") or "").strip()
        episodes = item.get("episodes") or []
        for ep in episodes:
            stream = ep.get("stream_url")
            if not stream:
                continue
            ep_name = ep.get("name") or "Bölüm"
            logo_for_line = item_logo or ep.get("img") or ""
            group = item_name.replace('"', "'")
            lines.append(f'#EXTINF:-1 tvg-logo="{logo_for_line}" group-title="{group}",{ep_name}')
            lines.append(stream)
    _atomic_write(master_path, "\n".join(lines) + "\n")

# ============================
# ATV SCRAPER (YENİ VE GÜÇLENDİRİLMİŞ)
# ============================

BASE_URL = "https://www.atv.com.tr/"
SERIES_URL = urljoin(BASE_URL, "diziler")
PROGRAMS_URL = urljoin(BASE_URL, "programlar")
STREAM_API_URL = "https://vms.atv.com.tr/vms/api/Player/GetVideoPlayer"

REQUEST_TIMEOUT = 25
REQUEST_PAUSE = 0.1
BACKOFF_FACTOR = 0.5
MAX_RETRIES = 5

DEFAULT_HEADERS = {
    "Referer": BASE_URL,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("atv-scraper")

SESSION = requests.Session()
retries = Retry(total=MAX_RETRIES, backoff_factor=BACKOFF_FACTOR, status_forcelist=(429, 500, 502, 503, 504))
SESSION.mount("https://", HTTPAdapter(max_retries=retries))
SESSION.headers.update(DEFAULT_HEADERS)

def get_soup(url: str) -> Optional[BeautifulSoup]:
    time.sleep(REQUEST_PAUSE)
    try:
        r = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return BeautifulSoup(r.content, "html.parser")
    except Exception as e:
        log.warning("GET %s hatası: %s", url, e)
        return None

def get_json(url: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    time.sleep(REQUEST_PAUSE)
    try:
        r = SESSION.get(url, timeout=REQUEST_TIMEOUT, params=params)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("JSON %s hatası: %s", url, e)
        return None

def get_content_list(page_url: str, content_type: str) -> List[Dict[str, str]]:
    """Verilen URL'den (diziler/programlar) içerik listesini çeker."""
    log.info("%s listesi alınıyor...", content_type.capitalize())
    content_list: List[Dict[str, str]] = []
    soup = get_soup(page_url)
    if not soup:
        log.error("%s listesi sayfası alınamadı.", content_type.capitalize())
        return content_list

    # SİTENİN YENİ YAPISINA UYGUN SEÇİCİ: 'article' etiketleri
    items = soup.select("article.widget-item a")
    for a_tag in items:
        img_tag = a_tag.find("img")
        if not (a_tag.get("href") and img_tag):
            continue

        url = urljoin(BASE_URL, a_tag["href"])
        name = img_tag.get("alt", "İsimsiz İçerik").strip()
        img = urljoin(BASE_URL, img_tag.get("data-src") or img_tag.get("src") or "")
        
        content_list.append({"name": name, "url": url, "img": img, "type": content_type})
    
    log.info("%d adet %s bulundu.", len(content_list), content_type)
    return content_list

def get_episodes_for_content(content_url: str) -> List[Dict[str, str]]:
    """Bir içeriğin 'bölümler' sayfasından tüm bölümleri alır."""
    episodes_url = urljoin(content_url.rstrip('/') + "/", "bolumler")
    all_episodes: List[Dict[str, str]] = []
    soup = get_soup(episodes_url)
    if not soup:
        return all_episodes

    items = soup.select("article.widget-item a")
    for a_tag in items:
        img_tag = a_tag.find("img")
        name_div = a_tag.select_one("div.name")
        if not (a_tag.get("href") and name_div):
            continue

        ep_url = urljoin(BASE_URL, a_tag["href"])
        ep_name = name_div.get_text(strip=True)
        ep_img = urljoin(BASE_URL, img_tag.get("data-src") or img_tag.get("src") or "")
        
        all_episodes.append({"name": ep_name, "url": ep_url, "img": ep_img})
    return all_episodes

def get_stream_url(episode_url: str) -> Optional[str]:
    """Bölüm sayfasından video ID'sini alıp API'den stream URL'sini çeker."""
    soup = get_soup(episode_url)
    if not soup: return None

    video_container = soup.find("div", {"id": "video-container", "data-videoid": True})
    if not video_container:
        log.warning("Video ID bulunamadı: %s", episode_url)
        return None

    video_id = video_container["data-videoid"]
    api_response = get_json(STREAM_API_URL, params={"id": video_id})
    if not api_response:
        log.warning("API'den stream URL alınamadı, Video ID: %s", video_id)
        return None

    try:
        return api_response["data"]["video"]["url"]
    except (KeyError, TypeError):
        log.warning("API cevabında stream URL bulunamadı, Video ID: %s", video_id)
        return None

def run(start: int = 0, end: int = 0) -> List[Dict[str, Any]]:
    diziler = get_content_list(SERIES_URL, "dizi")
    programlar = get_content_list(PROGRAMS_URL, "program")
    
    all_content = diziler + programlar
    log.info("Toplam %d içerik (dizi/program) bulundu. İşleme başlanıyor.", len(all_content))

    if not all_content:
        log.error("Hiç içerik bulunamadı. İşlem durduruldu.")
        return []

    output: List[Dict[str, Any]] = []
    end_index = len(all_content) if end == 0 else min(end, len(all_content))
    start_index = max(0, start)

    for i in tqdm(range(start_index, end_index), desc="İçerikler"):
        content = all_content[i]
        log.info("[%d/%d] %s (%s)", i + 1, end_index, content["name"], content["type"].upper())

        episodes = get_episodes_for_content(content["url"])
        if not episodes:
            log.warning("  -> Bölüm bulunamadı: %s", content["name"])
            continue

        temp_content = dict(content)
        temp_content["episodes"] = []

        for ep in tqdm(episodes, desc="   Bölümler", leave=False):
            stream_url = get_stream_url(ep["url"])
            if stream_url:
                temp_episode = dict(ep)
                temp_episode["stream_url"] = stream_url
                temp_content["episodes"].append(temp_episode)

        if temp_content["episodes"]:
            output.append(temp_content)

    return output

def save_outputs(data: List[Dict[str, Any]]) -> None:
    """Tüm M3U dosyalarını ilgili klasörlere ve birleşik olarak kaydeder."""
    if not data:
        log.warning("Kaydedilecek veri bulunamadı. M3U oluşturulmadı.")
        return
    try:
        # 1. Ayrı listeler oluştur
        diziler_data = [item for item in data if item.get("type") == "dizi"]
        programlar_data = [item for item in data if item.get("type") == "program"]

        # 2. Kategori bazlı M3U dosyalarını kendi klasörlerine kaydet
        if diziler_data:
            create_m3us_for_category(DIZILER_M3U_DIR, diziler_data)
            log.info("%d dizi için M3U dosyaları '%s' klasörüne oluşturuldu.", len(diziler_data), DIZILER_M3U_DIR)
        
        if programlar_data:
            create_m3us_for_category(PROGRAMLAR_M3U_DIR, programlar_data)
            log.info("%d program için M3U dosyaları '%s' klasörüne oluşturuldu.", len(programlar_data), PROGRAMLAR_M3U_DIR)

        # 3. Tüm içeriği tek bir ana dosyada birleştir
        create_single_m3u(ALL_M3U_DIR, data, ALL_M3U_NAME)
        log.info("Tüm içerikleri içeren birleşik M3U dosyası (%s.m3u) oluşturuldu.", ALL_M3U_NAME)

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