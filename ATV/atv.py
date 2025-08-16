#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ATV.com.tr scraper (yalnızca M3U üretir) - GÜNCELLENMİŞ SÜRÜM
- ATV.m3u       → bu .py dosyasının olduğu klasöre
- programlar/* → her dizi için ayrı M3U (aynı klasör altındaki 'programlar' klasörüne)

Kullanım:
  python atv.py
  python atv.py 10       (ilk 10 diziyi alır)
  python atv.py 5 15     (5. diziden 15. diziye kadar alır)
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
# ÇIKTI KONUMU (.py ile aynı klasördeki 'ATV' klasörü)
# ============================
BASE_DIR = Path(__file__).resolve().parent

# Tek dosyalık birleşik liste: ./ATV.m3u
ALL_M3U_DIR = str(BASE_DIR)
ALL_M3U_NAME = "ATV"

# Dizi bazlı listeler: ./programlar/*.m3u
SERIES_M3U_DIR = str(BASE_DIR / "programlar")
SERIES_MASTER = False

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
    return slugify((name or "dizi").lower()) + ".m3u"

def create_m3us(channel_folder_path: str,
                data: List[Dict[str, Any]],
                master: bool = False,
                base_url: str = "") -> None:
    _ensure_dir(channel_folder_path)
    master_lines: List[str] = ["#EXTM3U"] if master else []

    if base_url and not base_url.endswith(("/", "\\")):
        base_url = base_url + "/"

    for serie in (data or []):
        episodes = serie.get("episodes") or []
        if not episodes:
            continue

        series_name = (serie.get("name") or "Bilinmeyen Seri").strip()
        series_logo = (serie.get("img") or "").strip()
        plist_name = _safe_series_filename(series_name)
        plist_path = os.path.join(channel_folder_path, plist_name)

        lines: List[str] = ["#EXTM3U"]
        for ep in episodes:
            stream = ep.get("stream_url")
            if not stream:
                continue
            ep_name = ep.get("name") or "Bölüm"
            logo_for_line = series_logo or ep.get("img") or ""
            group = series_name.replace('"', "'")
            lines.append(f'#EXTINF:-1 tvg-logo="{logo_for_line}" group-title="{group}",{ep_name}')
            lines.append(stream)

        if len(lines) > 1:
            _atomic_write(plist_path, "\n".join(lines) + "\n")
            if master:
                master_lines.append(f'#EXTINF:-1 tvg-logo="{series_logo}", {series_name}')
                master_lines.append(f'{base_url}{plist_name}')

    if master:
        master_path = os.path.join(channel_folder_path, "0.m3u")
        _atomic_write(master_path, "\n".join(master_lines) + "\n")

def create_single_m3u(channel_folder_path: str,
                      data: List[Dict[str, Any]],
                      custom_path: str = "0") -> None:
    _ensure_dir(channel_folder_path)
    master_path = os.path.join(channel_folder_path, f"{custom_path}.m3u")

    lines: List[str] = ["#EXTM3U"]
    for serie in (data or []):
        series_name = (serie.get("name") or "Bilinmeyen Seri").strip()
        series_logo = (serie.get("img") or "").strip()
        episodes = serie.get("episodes") or []
        for ep in episodes:
            stream = ep.get("stream_url")
            if not stream:
                continue
            ep_name = ep.get("name") or "Bölüm"
            logo_for_line = series_logo or ep.get("img") or ""
            group = series_name.replace('"', "'")
            lines.append(f'#EXTINF:-1 tvg-logo="{logo_for_line}" group-title="{group}",{ep_name}')
            lines.append(stream)

    _atomic_write(master_path, "\n".join(lines) + "\n")

# ============================
# ATV SCRAPER (GÜNCELLENMİŞ)
# ============================

BASE_URL = "https://www.atv.com.tr/"
SERIES_LIST_URL = urljoin(BASE_URL, "diziler")
STREAM_API_URL = "https://vms.atv.com.tr/vms/api/Player/GetVideoPlayer"

REQUEST_TIMEOUT = 20
REQUEST_PAUSE = 0.1
BACKOFF_FACTOR = 0.5
MAX_RETRIES = 5

DEFAULT_HEADERS = {
    "Referer": BASE_URL,
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("atv-scraper")

SESSION = requests.Session()
retries = Retry(
    total=MAX_RETRIES,
    backoff_factor=BACKOFF_FACTOR,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET"]),
    raise_on_status=False,
)
SESSION.mount("https://", HTTPAdapter(max_retries=retries))
SESSION.mount("http://", HTTPAdapter(max_retries=retries))
SESSION.headers.update(DEFAULT_HEADERS)

def get_soup(url: str, params: Optional[Dict[str, Any]] = None) -> Optional[BeautifulSoup]:
    time.sleep(REQUEST_PAUSE)
    try:
        r = SESSION.get(url, timeout=REQUEST_TIMEOUT, params=params)
        r.raise_for_status()
        return BeautifulSoup(r.content, "html.parser")
    except Exception as e:
        log.warning("GET %s hatası: %s", url, e)
        return None

def get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    time.sleep(REQUEST_PAUSE)
    try:
        r = SESSION.get(url, timeout=REQUEST_TIMEOUT, params=params)
        r.raise_for_status()
        return r.json()
    except (requests.exceptions.JSONDecodeError, Exception) as e:
        log.warning("JSON %s hatası: %s", url, e)
        return None

def get_all_programs() -> List[Dict[str, str]]:
    """'atv.com.tr/diziler' sayfasından tüm dizilerin listesini alır."""
    log.info("Dizi listesi alınıyor...")
    all_programs: List[Dict[str, str]] = []
    soup = get_soup(SERIES_LIST_URL)
    if not soup:
        log.error("Dizi listesi sayfası alınamadı.")
        return all_programs

    # GÜNCELLENDİ: Sitenin yeni HTML yapısına göre doğru seçici kullanıldı.
    program_boxes = soup.select("div.brand-item a")
    for a_tag in program_boxes:
        img_tag = a_tag.find("img")
        
        if not (a_tag and a_tag.get("href") and img_tag):
            continue

        program_url = urljoin(BASE_URL, a_tag["href"])
        program_name = img_tag.get("alt", "İsimsiz Program").strip()
        program_img = ""
        if img_tag:
            program_img = img_tag.get("data-src") or img_tag.get("src") or ""
            program_img = urljoin(BASE_URL, program_img)

        all_programs.append({"name": program_name, "url": program_url, "img": program_img})
        
    log.info("%d adet dizi bulundu.", len(all_programs))
    return all_programs

def get_episodes_for_program(program_url: str) -> List[Dict[str, str]]:
    """Bir dizinin 'bölümler' sayfasından tüm bölümleri alır."""
    episodes_url = urljoin(program_url + "/", "bolumler")
    all_episodes: List[Dict[str, str]] = []
    soup = get_soup(episodes_url)
    if not soup:
        return all_episodes

    # GÜNCELLENDİ: Bölümler sayfasının yeni HTML yapısına uygun seçici.
    episode_items = soup.select("div.widget-item a")
    for a_tag in episode_items:
        img_tag = a_tag.find("img")
        name_div = a_tag.select_one("div.name")

        if not (a_tag and a_tag.get("href") and name_div):
            continue

        ep_url = urljoin(BASE_URL, a_tag["href"])
        ep_name = name_div.get_text(strip=True)
        ep_img = ""
        if img_tag:
            ep_img = img_tag.get("data-src") or img_tag.get("src") or ""
            ep_img = urljoin(BASE_URL, ep_img)

        all_episodes.append({"name": ep_name, "url": ep_url, "img": ep_img})
    return all_episodes

def get_stream_url(episode_url: str) -> Optional[str]:
    """Bölüm sayfasından video ID'sini alıp API'den stream URL'sini çeker."""
    soup = get_soup(episode_url)
    if not soup:
        return None

    video_container = soup.find("div", {"id": "video-container"})
    if not (video_container and video_container.get("data-videoid")):
        log.warning("Video ID bulunamadı: %s", episode_url)
        return None

    video_id = video_container["data-videoid"]
    
    api_response = get_json(STREAM_API_URL, params={"id": video_id})
    if not api_response:
        log.warning("API'den stream URL alınamadı, Video ID: %s", video_id)
        return None

    try:
        stream_url = api_response["data"]["video"]["url"]
        return stream_url
    except (KeyError, TypeError):
        log.warning("API cevabında stream URL bulunamadı, Video ID: %s", video_id)
        return None

def run(start: int = 0, end: int = 0) -> Dict[str, Any]:
    output: List[Dict[str, Any]] = []
    programs_list = get_all_programs()
    if not programs_list:
        log.error("Hiç program bulunamadı. İşlem durduruldu.")
        return {"programs": []}

    end_index = len(programs_list) if end == 0 else min(end, len(programs_list))
    start_index = max(0, start)

    for i in tqdm(range(start_index, end_index), desc="Programlar"):
        program = programs_list[i]
        log.info("[%d/%d] %s", i + 1, end_index, program.get("name", ""))

        episodes = get_episodes_for_program(program["url"])
        if not episodes:
            log.warning("  -> Bölüm bulunamadı: %s", program.get("name"))
            continue

        temp_program = dict(program)
        temp_program["episodes"] = []

        for ep in tqdm(episodes, desc="   Bölümler", leave=False):
            stream_url = get_stream_url(ep["url"])
            if stream_url:
                temp_episode = dict(ep)
                temp_episode["stream_url"] = stream_url
                temp_program["episodes"].append(temp_episode)

        if temp_program["episodes"]:
            output.append(temp_program)

    return {"programs": output}

def save_outputs_only_m3u(data: Dict[str, Any]) -> None:
    """Sadece M3U dosyaları üretir."""
    programs = data.get("programs", [])
    if not programs:
        log.warning("Kaydedilecek veri bulunamadı. M3U oluşturulmadı.")
        return
    try:
        create_single_m3u(ALL_M3U_DIR, programs, ALL_M3U_NAME)
        create_m3us(SERIES_M3U_DIR, programs, master=SERIES_MASTER)
        log.info("M3U dosyaları başarıyla oluşturuldu.")
    except Exception as e:
        log.error("M3U oluşturma hatası: %s", e)

def parse_args(argv: List[str]) -> Tuple[int, int]:
    start, end = 0, 0
    if len(argv) >= 2:
        try:
            end = int(argv[1])
        except Exception:
            pass
    if len(argv) >= 3:
        try:
            start = int(argv[1])
            end = int(argv[2])
        except Exception:
            pass
    return start, end

def main():
    start, end = parse_args(sys.argv)
    data = run(start=start, end=end)
    save_outputs_only_m3u(data)

if __name__ == "__main__":
    main()