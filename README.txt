# YT Downloader — macOS App

A clean YouTube/Shorts downloader with a native GUI.

## Setup (one time)

1. Make sure you have Python 3 installed (comes with macOS, or use https://python.org)
2. Open Terminal, navigate to this folder:
   ```
   cd ~/Downloads/ytdl_app
   ```
3. Run the build script:
   ```
   bash build_mac.sh
   ```
4. Your app will be at `dist/YTDownloader.app`
5. Drag it to `/Applications` to install it

## Running without building

If you just want to run it directly without building an .app:

```bash
pip3 install yt-dlp
python3 main.py
```

## Features

- Paste any YouTube or YouTube Shorts URL
- Choose format: mp4, mp3, webm, m4a
- Choose quality: Best, 1080p, 720p, 480p, 360p
- Pick your save folder
- Live download progress + speed + ETA

## Requirements

- macOS 10.14+
- Python 3.8+
- ffmpeg (for merging video+audio) — install via Homebrew: `brew install ffmpeg`
  - Without ffmpeg, downloads still work but may be video-only for some formats
