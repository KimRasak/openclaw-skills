---
name: douyin-video-downloader
description: Download videos from Douyin (抖音) share links. Parses obfuscated share text to extract the real video URL and downloads watermark-free MP4. Use when the user shares a Douyin link or share text and wants to download the video.
---

# Douyin Video Downloader

从抖音分享链接（含混淆文字）解析并下载无水印视频。

## When to Use This Skill

Use this skill when you need to:
- Download a video from a Douyin share link or share text
- Extract the real video URL from obfuscated Douyin share text
- Get a watermark-free download link for a Douyin video

## Prerequisites

```bash
pip install requests
```

## Usage

```bash
python scripts/douyin_download.py <SHARE_TEXT_OR_URL> [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `-o`, `--output` | `output/` | Output directory |
| `--info-only` | off | Only print video info and download URL, don't download |

### Examples

```bash
# From share text (copied from Douyin app)
python scripts/douyin_download.py "7.08 复制打开抖音，看看【xxx】的作品 https://v.douyin.com/aBcDeFg/"

# From short URL directly
python scripts/douyin_download.py "https://v.douyin.com/aBcDeFg/"

# From full video URL
python scripts/douyin_download.py "https://www.douyin.com/video/7123456789012345678"

# Specify output directory
python scripts/douyin_download.py "https://v.douyin.com/aBcDeFg/" -o my_videos/

# Only get the download URL without downloading
python scripts/douyin_download.py "https://v.douyin.com/aBcDeFg/" --info-only
```

## How It Works

1. 从分享文本中用正则提取 `v.douyin.com` 短链接
2. 跟随 302 重定向获取完整视频页面 URL
3. 从 URL 中提取视频 ID
4. 通过 iesdouyin API 或页面解析获取视频元数据
5. 提取最高画质无水印视频地址（`playwm` → `play`）
6. 流式下载 MP4 文件，显示进度

## Notes

- 支持从抖音 App 分享的混淆文字中自动提取链接
- 自动选择最高画质
- 下载无水印版本
- 中文文件名正常保留
- 仅依赖 `requests`，无需 yt-dlp
