---
name: bilibili-video-transcriber
description: Download audio from Bilibili videos and transcribe to text using faster-whisper (GPU). Two-step pipeline — download audio via yt-dlp, then transcribe with Whisper large-v3. Use when the user wants to download B站 video audio, transcribe Bilibili videos to text, or convert online video speech to text files.
---

# Bilibili Video Transcriber

从 Bilibili (B站) 视频下载音频，并使用 faster-whisper 在 GPU 上转录为文本。

## When to Use This Skill

Use this skill when you need to:
- Download audio from a Bilibili video and transcribe it to text
- Extract speech content from B站 videos (lectures, podcasts, live streams)
- Convert Bilibili video audio to a readable text file

## Prerequisites

### 1. yt-dlp + ffmpeg (audio download)

```bash
pip install yt-dlp
conda install -y ffmpeg -c conda-forge
```

### 2. faster-whisper (audio transcription, GPU)

```bash
pip install faster-whisper
```

Requires CUDA-capable GPU and PyTorch with CUDA support.

## Workflow

### Step 1 — Download Audio

```bash
yt-dlp -x --audio-format mp3 --audio-quality 0 \
  -o "<OUTPUT_DIR>/%(title)s.%(ext)s" \
  "<BILIBILI_URL>"
```

| Flag | Description |
|------|-------------|
| `-x` | Extract audio only |
| `--audio-format mp3` | Convert to MP3 (also supports: aac, flac, m4a, opus, wav) |
| `--audio-quality 0` | Best quality (0=best, 10=worst) |
| `-o` | Output template. `%(title)s` = video title, `%(ext)s` = extension |

### Step 2 — Transcribe to Text

```bash
python3 scripts/transcribe_audio.py <AUDIO_FILE> [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `-o`, `--output` | `<audio>.txt` | Output text file path |
| `-m`, `--model` | `large-v3` | Model size: `tiny` / `base` / `small` / `medium` / `large-v3` |
| `-l`, `--language` | auto-detect | Language code: `zh`, `en`, `ja`, etc. |
| `--device` | `cuda` | `cuda` or `cpu` |
| `--compute-type` | `float16` | `float16` / `int8` / `int8_float16` |
| `--beam-size` | `5` | Beam search width |
| `--timestamps` | off | Include `[HH:MM:SS -> HH:MM:SS]` timestamps |

### Full Example

```bash
# 1. Download audio
yt-dlp -x --audio-format mp3 --audio-quality 0 \
  -o "output/%(title)s.%(ext)s" \
  "https://www.bilibili.com/video/BV1dKPrzPEwc/"

# 2. Transcribe
python3 scripts/transcribe_audio.py "output/视频标题.mp3" \
  -o "output/视频标题.txt" \
  -l zh --timestamps
```

## Model Selection Guide

| Model | VRAM | Speed | Accuracy | Recommended For |
|-------|------|-------|----------|-----------------|
| `tiny` | ~1 GB | fastest | lowest | Quick preview |
| `base` | ~1 GB | fast | low | Draft transcription |
| `small` | ~2 GB | moderate | good | General use |
| `medium` | ~5 GB | slow | high | High-quality transcription |
| `large-v3` | ~10 GB | slowest | highest | Best accuracy, multilingual |

For Chinese content, `large-v3` is strongly recommended for best accuracy.

## Output

- Audio file: `<output_dir>/<video_title>.mp3`
- Text file: `<output_dir>/<video_title>.txt` (plain text, one segment per line)
- With `--timestamps`: each line prefixed with `[HH:MM:SS -> HH:MM:SS]`

## Notes

- Bilibili URL query parameters (e.g., `?spm_id_from=...`) are safely ignored
- For multi-part videos (分P), use `--playlist-items` to select specific parts
- Chinese characters in filenames are preserved correctly
- No Bilibili login required for public videos; for members-only content use `--cookies`
- VAD (Voice Activity Detection) is enabled by default to skip silence and improve speed
- First run downloads the Whisper model (~3 GB for large-v3); subsequent runs use cached model
