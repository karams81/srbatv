name: Generate YabanciDizi M3U Playlist

on:
  # Her 6 saatte bir otomatik olarak çalıştırır
  schedule:
    - cron: '0 */6 * * *'
  # Manuel olarak çalıştırma imkanı sunar
  workflow_dispatch:

jobs:
  generate-playlist:
    runs-on: ubuntu-latest
    timeout-minutes: 25 # İşlem süresini biraz daha uzun tutalım

    permissions:
      contents: write # Repoya yazma izni

    steps:
    - name: Checkout repository
      # Kodu ve mevcut M3U dosyasını çalışma alanına kopyalar
      uses: actions/checkout@v4

    - name: Set up Python
      # Python 3.10 ortamını kurar
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'

    - name: Install dependencies
      # Gerekli olan 'requests' kütüphanesini yükler
      run: pip install requests

    - name: Run M3U Generator
      # Python betiğini çalıştırarak M3U dosyasını oluşturur
      # Betik adı 'yabancidizi_generator.py' olmalı
      run: python yabancidizi_generator.py

    - name: Commit and Push to repository
      # Oluşturulan M3U dosyasında bir değişiklik varsa repoya gönderir
      run: |
        git config --global user.name "GitHub Actions Bot"
        git config --global user.email "actions@github.com"
        
        # Dosya adını betiktekiyle aynı yapın
        git add yabancidizi_full.m3u
        
        # Eğer bir değişiklik yoksa commit atma
        if git diff --staged --quiet; then
          echo "Değişiklik bulunamadı. Commit atılmayacak."
        else
          git commit -m "Auto-Update: YabanciDizi M3U Playlist [$(date)]"
          git push
        fi