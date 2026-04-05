---
name: bilibili-video-downloader
description: Download audio/video from Bilibili (B站) videos using yt-dlp. Supports audio extraction (mp3/aac/flac/wav), best quality selection, multi-part videos, and members-only content with cookies. Use when the user wants to download B站 video audio or video files.
---

# Bilibili Video Downloader

从 Bilibili (B站) 视频下载音频或视频文件，使用 yt-dlp 实现。

## When to Use This Skill

Use this skill when you need to:
- Download audio from a Bilibili video
- Extract audio track from B站 videos (lectures, podcasts, live streams)
- Download Bilibili video files for offline use

## Prerequisites

### yt-dlp

```bash
pip install yt-dlp   # in base env, if not already installed
```

ffmpeg is required for audio format conversion. Pre-installed in the whisperx env
(`/gluster_osa_cv/user/jinzili/env/whisperx`) via conda-forge, or install system-wide.

## Usage

### Download Audio

```bash
python scripts/bilibili_download.py <BILIBILI_URL> [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `-o`, `--output` | `output/` | Output directory |
| `--audio-format` | `mp3` | Audio format: `mp3` / `aac` / `flac` / `m4a` / `opus` / `wav` |
| `--audio-quality` | `0` | Audio quality (0=best, 10=worst) |
| `--cookies` | none | Path to cookies file (for members-only content) |
| `--playlist-items` | all | Select specific parts for multi-part videos (e.g. `1-3`, `2`) |

### Examples

```bash
# Basic: download audio as mp3
python scripts/bilibili_download.py "https://www.bilibili.com/video/BV1dKPrzPEwc/"

# Specify output directory and format
python scripts/bilibili_download.py "https://www.bilibili.com/video/BV1dKPrzPEwc/" \
  -o my_audio/ --audio-format flac

# Multi-part video, download parts 1-3
python scripts/bilibili_download.py "https://www.bilibili.com/video/BV1dKPrzPEwc/" \
  --playlist-items 1-3

# Members-only content with cookies
python scripts/bilibili_download.py "https://www.bilibili.com/video/BV1dKPrzPEwc/" \
  --cookies cookies.txt
```

### Manual yt-dlp Command

If you prefer to use yt-dlp directly:

```bash
yt-dlp -x --audio-format mp3 --audio-quality 0 \
  -o "<OUTPUT_DIR>/%(title)s.%(ext)s" \
  "<BILIBILI_URL>"
```

| Flag | Description |
|------|-------------|
| `-x` | Extract audio only |
| `--audio-format mp3` | Convert to MP3 |
| `--audio-quality 0` | Best quality (0=best, 10=worst) |
| `-o` | Output template. `%(title)s` = video title, `%(ext)s` = extension |

## Notes

- Bilibili URL query parameters (e.g., `?spm_id_from=...`) are safely ignored
- For multi-part videos (分P), use `--playlist-items` to select specific parts
- Chinese characters in filenames are preserved correctly
- No Bilibili login required for public videos; for members-only content use `--cookies`
