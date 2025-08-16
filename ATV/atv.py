#!/usr/bin/env python3
# -*- aoding: utf-8 -*-

"""
ATV.com.tr Scraper (Diziler ve Programlar) - ENGEL AŞAN NİHAİ SÜRÜM
Bu script, Playwright kullanarak gerçek bir tarayıcıyı otomatize eder.
Sayfalar açıldığında çıkan Çerez Onay Ekranı (Cookie Consent) gibi engelleri
otomatik olarak bularak tıklar ve ardından içeriği çeker. Bu, en güvenilir
ve kalıcı çözümdür.
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
from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeoutError

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
STREAM_API_URL = "https://vms.atv.com.tr/vms/api/Player/GetVideoPlayer"

# GITHUB ACTIONS İÇİN MAKSİMUM ZAMAN AŞIMLARI (milisanİye)
PAGE_TIMEOUT = 180000  # 180 saniye (3 dakika)
SELECTOR_TIMEOUT = 180000 # 180 saniye (3 dakika)

# Loglama ayarları
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("atv-scraper")

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
# 3. VERİ ÇEKME FONKSİYONLARI (ENGEL AŞMA ÖZELLİKLİ)
# ============================

def handle_consent(page: Page) -> None:
    """Sayfadaki Çerez Onay Ekranını bulur ve kapatır."""
    consent_button_selector = "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll"
    try:
        log.info("Çerez Onay Ekranı (engel) kontrol ediliyor...")
        button = page.locator(consent_button_selector).first
        if button.is_visible(timeout=15000): # 15 saniye içinde görünürse
            log.info("-> Onay ekranı bulundu, 'Tümünü Kabul Et' butonuna tıklanıyor...")
            button.click()
            page.wait_for_timeout(2000) # Tıklama sonrası sayfanın toparlanması için kısa bekleme
            log.info("-> Engel başarıyla kaldırıldı.")
        else:
            log.info("-> Onay ekranı bulunamadı, devam ediliyor.")
    except PlaywrightTimeoutError:
        log.info("-> Onay ekranı belirtilen sürede çıkmadı, devam ediliyor.")
    except Exception as e:
        log.warning("-> Onay ekranı işlenirken bir hata oluştu: %s", e)

def get_content_list(page: Page, url: str, content_type: str) -> List[Dict[str, str]]:
    """Playwright kullanarak verilen sayfadaki tüm içerikleri (dizi/program) çeker."""
    log.info("'%s' sayfasından '%s' listesi çekiliyor...", url, content_type)
    content_list = []
    try:
        page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
        handle_consent(page) # KRİTİK ADIM: İçeriği aramadan önce engeli kaldır
        
        log.info("İçerik listesinin yüklenmesi bekleniyor...")
        page.wait_for_selector("article.widget-item a", timeout=SELECTOR_TIMEOUT)
        
        soup = BeautifulSoup(page.content(), "html.parser")
        items = soup.select("article.widget-item a")
        
        if not items:
            log.warning("-> Sayfa yüklendi ancak '%s' için içerik bulunamadı.", content_type)
            return []

        for a_tag in items:
            img_tag = a_tag.find("img")
            if not (a_tag.get("href") and img_tag): continue
            
            content_list.append({
                "name": img_tag.get("alt", "İsimsiz").strip(),
                "url": urljoin(BASE_URL, a_tag["href"]),
                "img": urljoin(BASE_URL, img_tag.get("data-src") or img_tag.get("src") or ""),
                "type": content_type
            })
        log.info("-> Başarılı: %d adet %s bulundu.", len(content_list), content_type)
        return content_list
    except PlaywrightTimeoutError:
        log.error("-> ZAMAN AŞIMI! Sayfa veya içerik %d saniyede yüklenemedi: %s", PAGE_TIMEOUT / 1000, url)
        return []
    except Exception as e:
        log.error("-> '%s' listesi çekilirken beklenmedik hata: %s", content_type, e)
        return []

def get_episodes_and_streams(page: Page, content_url: str, session: requests.Session) -> List[Dict[str, str]]:
    """Bir içeriğin tüm bölümlerini ve her bölümün yayın linkini çeker."""
    episodes_url = urljoin(content_url.rstrip('/') + "/", "bolumler")
    processed_episodes = []
    try:
        page.goto(episodes_url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
        handle_consent(page)
        page.wait_for_selector("article.widget-item a", timeout=SELECTOR_TIMEOUT)
        
        soup = BeautifulSoup(page.content(), "html.parser")
        episode_links = soup.select("article.widget-item a")

        for ep_link in tqdm(episode_links, desc=f"   -> Bölümler", leave=False):
            ep_name_div = ep_link.select_one("div.name")
            if not (ep_link.get("href") and ep_name_div): continue
            
            ep_url = urljoin(BASE_URL, ep_link["href"])
            ep_name = ep_name_div.get_text(strip=True)
            
            try:
                page.goto(ep_url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
                video_container = page.wait_for_selector("div#video-container[data-videoid]", timeout=SELECTOR_TIMEOUT)
                video_id = video_container.get_attribute("data-videoid")
                
                if video_id:
                    response = session.get(STREAM_API_URL, params={"id": video_id})
                    response.raise_for_status()
                    stream_url = response.json()["data"]["video"]["url"]
                    processed_episodes.append({"name": ep_name, "stream_url": stream_url})
            except (PlaywrightTimeoutError, requests.RequestException, KeyError):
                log.warning("--> '%s' için yayın linki alınamadı.", ep_name)
                continue
        return processed_episodes
    except PlaywrightTimeoutError:
        log.error("-> Bölüm sayfası zaman aşımına uğradı: %s", episodes_url)
        return []
    except Exception as e:
        log.error("-> Bölümler çekilirken hata: %s", e)
        return []


# ============================
# 4. ANA İŞLEM AKIŞI
# ============================
def run() -> None:
    with sync_playwright() as p:
        log.info("Playwright başlatılıyor ve Chromium tarayıcısı açılıyor...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        diziler = get_content_list(page, DIZILER_PAGE_URL, "dizi")
        programlar = get_content_list(page, PROGRAMLAR_PAGE_URL, "program")
        
        all_content = diziler + programlar
        if not all_content:
            log.critical("Hiçbir dizi veya program bulunamadı. İşlem durduruldu.")
            browser.close()
            return
            
        log.info("Toplam %d içerik bulundu. Bölümler ve yayın linkleri çekilecek...", len(all_content))
        
        api_session = requests.Session()
        api_session.headers.update({"Referer": BASE_URL})

        processed_data = []

        for content in tqdm(all_content, desc="Tüm İçerikler"):
            log.info("İşleniyor: %s (%s)", content["name"], content["type"].upper())
            episodes_with_streams = get_episodes_and_streams(page, content["url"], api_session)
            
            if episodes_with_streams:
                temp_content = dict(content)
                temp_content["episodes"] = episodes_with_streams
                processed_data.append(temp_content)

        browser.close()
        log.info("Tarayıcı kapatıldı.")

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