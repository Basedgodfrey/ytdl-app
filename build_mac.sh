#!/bin/bash
# build_mac.sh — Run this on your Mac to create YTDownloader.app

echo "Installing dependencies..."
pip3 install yt-dlp pyinstaller --break-system-packages 2>/dev/null || pip3 install yt-dlp pyinstaller

echo "Building .app bundle..."
pyinstaller \
  --onefile \
  --windowed \
  --name "YTDownloader" \
  --hidden-import yt_dlp \
  main.py

echo ""
echo "Done! Your app is at: dist/YTDownloader.app"
echo "You can drag it to your Applications folder."
