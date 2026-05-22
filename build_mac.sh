#!/bin/bash
# build_mac.sh — builds YTDownloader.app for macOS Apple Silicon

PYTHON=/opt/homebrew/bin/python3
PYI=/opt/homebrew/bin/pyinstaller
FFMPEG=/opt/homebrew/bin/ffmpeg

echo "→ Checking dependencies..."
$PYTHON -c "import yt_dlp" 2>/dev/null || { echo "Missing yt-dlp. Run: brew install yt-dlp"; exit 1; }
$PYTHON -c "from PIL import Image" 2>/dev/null || { echo "Missing Pillow. Run: pip install pillow --break-system-packages"; exit 1; }
$PYTHON -c "import customtkinter" 2>/dev/null || { echo "Missing customtkinter. Run: pip install customtkinter --break-system-packages"; exit 1; }
[ -f "$FFMPEG" ] || { echo "Missing ffmpeg. Run: brew install ffmpeg"; exit 1; }

echo "→ Building Canopy.app..."
$PYI \
  --windowed \
  --name "Canopy" \
  --add-binary "$FFMPEG:." \
  --hidden-import yt_dlp \
  --hidden-import PIL \
  --hidden-import PIL.Image \
  --hidden-import PIL.ImageTk \
  --collect-all yt_dlp \
  --collect-all customtkinter \
  main.py

echo ""
if [ -d "dist/Canopy.app" ]; then
  echo "✓ Built: dist/Canopy.app"
  echo ""
  echo "To install: drag dist/Canopy.app to your Applications folder."
  echo "Or run now: open dist/Canopy.app"
else
  echo "✗ Build failed — check output above."
fi
