#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ATV.com.tr Scraper (Diziler ve Programlar) - API TABANLI NİHAİ ÇÖZÜM
Bu script, Playwright'ı tamamen terk ederek, ATV'nin bot korumasını aşmak
için doğrudan sitenin dahili API'sine, gerçek bir tarayıcıyı taklit eden
istekler gönderir. Bu yöntem en hızlı, en güvenilir ve en kalıcı çözümdür.
"""

import os
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
ALL_M3U_NAME = "ATV"
DIZILER_M3U_DIR = str(BASE_DIR / "diziler")
PROGRAMLAR_M3U_DIR = str(BASE_DIR / "programlar")

BASE_URL = "https://www.atv.com.tr/"
DIZILER_PAGE_URL = urljoin(BASE_URL, "diziler")
PROGRAMLAR_PAGE_URL = urljoin(BASE_URL, "programlar")
CONTENT_API_URL = urljoin(BASE_URL, "services/get-all-series-and-programs-by-category-slug")
STREAM_API_URL = "https://vms.atv.com.tr/vms/api/Player/GetVideoPlayer"

REQUEST_TIMEOUT = 45
MAX_RETRIES = 5

# GERÇEK BİR TARAYICIYI TAKLİT EDEN BAŞLIKLAR
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": BASE_URL.rstrip('/'),
    "Referer": BASE_URL,
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("atv-scraper")

# Otomatik tekrar deneme ve cookie yönetimi için Session
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
    return slugify((name or "icerik").lower()) + ".m3u"

def create_m3us_for_category(channel_folder_path: str, data: List[Dict[str, Any]]) -> None:
    _ensure_dir(channel_folder_path)
    for item in data:
        episodes = item.get("episodes") or []
        if not episodes: continue
        item_name = item.get("name", "Bilinmeyen").strip()
        item_logo = item.get("img", "").strip()
        plist_path = os.path.join(channel_folder_path, _safe_series_filename(item_name))
        lines = ["#EXTM3U"]
        for ep in episodes:
            stream = ep.get("stream_url")
            if not stream: continue
            ep_name = ep.get("name", "Bölüm")
            group = item_name.replace('"', "'")
            lines.append(f'#EXTINF:-1 tvg-logo="{item_logo}" group-title="{group}",{ep_name}')
            lines.append(stream)
        if len(lines) > 1: _atomic_write(plist_path, "\n".join(lines) + "\n")

def create_single_m3u(channel_folder_path: str, data: List[Dict[str, Any]], custom_path: str) -> None:
    _ensure_dir(channel_folder_path)
    master_path = os.path.join(channel_folder_path, f"{custom_path}.m3u")
    lines = ["#EXTM3U"]
    for item in data:
        item_name = item.get("name", "Bilinmeyen").strip()
        item_logo = item.get("img", "").strip()
        episodes = item.get("episodes", [])
        for ep in episodes:
            stream = ep.get("stream_url")
            if not stream: continue
            ep_name = ep.get("name", "Bölüm")
            group = item_name.replace('"', "'")
            lines.append(f'#EXTINF:-1 tvg-logo="{item_logo}" group-title="{group}",{ep_name}')
            lines.append(stream)
    _atomic_write(master_path, "\n".join(lines) + "\n")

# ============================
# 3. VERİ ÇEKME FONKSİYONLARI (API ODAKLI NİHAİ SÜRÜM)
# ============================

def get_content_from_api(page_url: str, slug: str, content_type: str) -> List[Dict[str, Any]]:
    """
    Önce sayfayı ziyaret ederek cookie ve token alır, sonra bu bilgilerle API'ye
    güvenli bir istek gönderir.
    """
    log.info("'%s' için kimlik bilgileri (cookie/token) alınıyor...", content_type)
    try:
        # 1. Adım: Sayfayı ziyaret et ve gerekli cookie/token'ları al
        response = SESSION.get(page_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        token_tag = soup.find("input", {"name": "__RequestVerificationToken"})
        
        if not token_tag or not token_tag.get("value"):
            log.error("-> KRİTİK: CSRF token bulunamadı! Site yapısı değişmiş.")
            return []
        
        token = token_tag["value"]
        log.info("-> Kimlik bilgileri başarıyla alındı.")

        # 2. Adım: Alınan kimlik bilgileriyle API'ye POST isteği gönder
        log.info("API'den '%s' listesi çekiliyor...", content_type)
        api_response = SESSION.post(
            CONTENT_API_URL,
            data={"slug": slug},
            headers={"__RequestVerificationToken": token, "Referer": page_url},
            timeout=REQUEST_TIMEOUT
        )
        api_response.raise_for_status()
        api_data = api_response.json()

        if not isinstance(api_data, list):
            log.error("-> API'den beklenen formatta veri gelmedi.")
            return []
        
        content_list = [
            {
                "name": item.get("Name", "İsimsiz").strip(),
                "url": urljoin(BASE_URL, item.get("Url", "")),
                "img": urljoin(BASE_URL, item.get("ImageUrl", "")),
                "type": content_type
            } for item in api_data
        ]
        log.info("-> Başarılı: %d adet %s bulundu.", len(content_list), content_type)
        return content_list

    except requests.RequestException as e:
        log.error("-> '%s' verisi çekilirken ağ hatası: %s", content_type, e)
        return []
    except Exception as e:
        log.error("-> '%s' verisi işlenirken beklenmedik hata: %s", content_type, e)
        return []

def get_episodes_and_streams(content_url: str) -> List[Dict[str, str]]:
    """Bir içeriğin bölümlerini ve yayın linklerini çeker."""
    episodes_url = urljoin(content_url.rstrip('/') + "/", "bolumler")
    processed_episodes = []
    try:
        response = SESSION.get(episodes_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        episode_links = soup.select("article.widget-item a")

        for ep_link in tqdm(episode_links, desc=f"   -> Bölümler", leave=False):
            ep_name_div = ep_link.select_one("div.name")
            if not (ep_link.get("href") and ep_name_div): continue
            
            ep_url = urljoin(BASE_URL, ep_link["href"])
            ep_name = ep_name_div.get_text(strip=True)
            
            try:
                ep_page_response = SESSION.get(ep_url, timeout=REQUEST_TIMEOUT)
                ep_page_response.raise_for_status()
                ep_soup = BeautifulSoup(ep_page_response.content, "html.parser")
                video_container = ep_soup.find("div", {"id": "video-container", "data-videoid": True})
                
                if video_container and video_container.get("data-videoid"):
                    video_id = video_container["data-videoid"]
                    stream_response = SESSION.get(STREAM_API_URL, params={"id": video_id})
                    stream_response.raise_for_status()
                    stream_url = stream_response.json()["data"]["video"]["url"]
                    processed_episodes.append({"name": ep_name, "stream_url": stream_url})
            except (requests.RequestException, KeyError, ValueError):
                log.warning("--> '%s' için yayın linki alınamadı.", ep_name)
                continue
        return processed_episodes
    except requests.RequestException:
        return []

# ============================
# 4. ANA İŞLEM AKIŞI
# ============================
def run() -> None:
    diziler = get_content_from_api(DIZILER_PAGE_URL, "diziler", "dizi")
    programlar = get_content_from_api(PROGRAMLAR_PAGE_URL, "programlar", "program")
    
    all_content = diziler + programlar
    if not all_content:
        log.critical("Hiçbir dizi veya program bulunamadı. İşlem durduruldu.")
        return
        
    log.info("Toplam %d içerik bulundu. Bölümler ve yayın linkleri çekilecek...", len(all_content))
    processed_data = []

    for content in tqdm(all_content, desc="Tüm İçerikler"):
        log.info("İşleniyor: %s (%s)", content["name"], content["type"].upper())
        episodes_with_streams = get_episodes_and_streams(content["url"])
        
        if episodes_with_streams:
            temp_content = dict(content)
            temp_content["episodes"] = episodes_with_streams
            processed_data.append(temp_content)

    if not processed_data:
        log.error("Hiçbir bölüm için geçerli yayın linki bulunamadı. M3U dosyaları oluşturulmayacak.")
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
        log.critical("M3U dosyaları oluşturulurken hata: %s", e, exc_info=True)

if __name__ == "__main__":
    run()