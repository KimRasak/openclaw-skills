---
name: bilibili-video-transcriber
description: Download audio from Bilibili videos and transcribe to text using faster-whisper (GPU). Supports multi-GPU parallel transcription and speaker diarization via pyannote.audio. Use when the user wants to download B站 video audio, transcribe Bilibili videos to text, or convert online video speech to text files.
---

# Bilibili Video Transcriber

从 Bilibili (B站) 视频下载音频，并使用 faster-whisper 在 GPU 上转录为文本。支持多 GPU 并行加速和说话人分离。

## When to Use This Skill

Use this skill when you need to:
- Download audio from a Bilibili video and transcribe it to text
- Extract speech content from B站 videos (lectures, podcasts, live streams)
- Convert Bilibili video audio to a readable text file
- Distinguish different speakers in a conversation (speaker diarization)

## Environment

A dedicated conda environment is set up at `/gluster_osa_cv/user/jinzili/env/whisperx` with all
dependencies pre-installed. **Always use this environment** to run the script:

```bash
/gluster_osa_cv/user/jinzili/env/whisperx/bin/python3 scripts/transcribe_audio.py ...
```

> **Why a separate env?** whisperx requires `transformers 4.x`, which conflicts with the base
> conda environment's `transformers 5.x` (used by Qwen3.5). The dedicated env isolates these
> incompatible versions.

Installed packages: torch 2.8.0+cu128, torchvision 0.23.0+cu128, transformers 4.57.x,
whisperx 3.8.2, faster-whisper 1.2.1, pyannote-audio 4.0.4, pydub, ffmpeg (conda-forge).

## Prerequisites

### 1. yt-dlp (audio download)

```bash
pip install yt-dlp   # in base env, if not already installed
```

ffmpeg is pre-installed in the whisperx env via conda-forge.

### 2. faster-whisper (audio transcription, GPU)

Pre-installed in `/gluster_osa_cv/user/jinzili/env/whisperx`. Requires CUDA-capable GPU.
The script enforces GPU availability at startup — if no CUDA GPU is detected, it exits immediately.

### 3. whisperx + pyannote (speaker diarization, optional)

Pre-installed in `/gluster_osa_cv/user/jinzili/env/whisperx`. Required only when using `--diarize`.
You must also:
1. Accept the model license at https://huggingface.co/pyannote/speaker-diarization-community-1
2. Accept the segmentation model license at https://huggingface.co/pyannote/segmentation-3.0
3. Set `HF_TOKEN` env var or pass `--hf-token <token>`

> **Important:** The model used is `pyannote/speaker-diarization-community-1`, **not**
> `speaker-diarization-3.1`. Make sure to accept the license for the correct model page.

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
/gluster_osa_cv/user/jinzili/env/whisperx/bin/python3 scripts/transcribe_audio.py <AUDIO_FILE> [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `-o`, `--output` | `<audio>.txt` | Output text file path |
| `-m`, `--model` | `large-v3` | Model size: `tiny` / `base` / `small` / `medium` / `large-v3` |
| `-l`, `--language` | auto-detect | Language code: `zh`, `en`, `ja`, etc. |
| `--beam-size` | `5` | Beam search width |
| `--timestamps` | off | Include `[HH:MM:SS -> HH:MM:SS]` timestamps |
| `--diarize` | off | Enable speaker diarization via WhisperX + pyannote (requires HF token) |
| `--num-speakers` | auto-detect | Number of speakers (improves diarization accuracy when known) |
| `--hf-token` | `$HF_TOKEN` | HuggingFace token for pyannote models |
| `--num-gpus` | all available | Number of GPUs for parallel transcription |

> **Note:** The script always runs on CUDA GPU with float16. If GPU is unavailable, the script
> exits with an error. When multiple GPUs are available, the audio is automatically split and
> transcribed in parallel across all GPUs.

### Full Example

```bash
# 1. Download audio
yt-dlp -x --audio-format mp3 --audio-quality 0 \
  -o "output/%(title)s.%(ext)s" \
  "https://www.bilibili.com/video/BV1dKPrzPEwc/"

# 2. Transcribe only (single GPU, with timestamps)
CUDA_VISIBLE_DEVICES=0 \
/gluster_osa_cv/user/jinzili/env/whisperx/bin/python3 scripts/transcribe_audio.py \
  "output/视频标题.mp3" -o "output/视频标题.txt" -l zh --timestamps

# 3. Transcribe with speaker diarization (7 GPUs parallel transcription)
HF_TOKEN=<your_token> \
/gluster_osa_cv/user/jinzili/env/whisperx/bin/python3 scripts/transcribe_audio.py \
  "output/视频标题.mp3" -o "output/视频标题.txt" \
  -l zh --diarize --num-speakers 2 --num-gpus 7
```

## Multi-GPU Parallel Transcription

When multiple GPUs are available, the script automatically:
1. Splits the audio into N chunks with a 10-second overlap between adjacent chunks (avoids cutting mid-sentence)
2. Spawns N independent subprocesses via `spawn`, each loading its own Whisper model on a dedicated GPU
3. Transcribes all chunks in parallel
4. Deduplicates segments in the overlap regions by midpoint timestamp, then merges results

Use `--num-gpus` to limit the number of GPUs (default: use all available). Use `--num-gpus 1` to force single-GPU mode.

In `--diarize` mode, `--num-gpus` applies to the transcription stage only. Alignment and
diarization always run on GPU 0 using the full audio (required for globally consistent speaker
embeddings).

**Measured performance** (1.8hr podcast, H100 x7, large-v3):
- Transcription (7 GPUs parallel): ~115s
- Alignment + diarization (GPU 0): ~73s
- Total: ~3 minutes

## Speaker Diarization

When `--diarize` is enabled, the script uses the **WhisperX pipeline**:
1. **Parallel transcription**: splits audio into N chunks, each GPU transcribes one chunk with whisperx
2. **Merge**: deduplicates overlap regions, produces full segment list
3. **Word-level alignment** (GPU 0, full audio): forces per-word timestamps for precise boundaries
4. **pyannote diarization** (GPU 0, full audio): runs `speaker-diarization-community-1` to detect speaker turns
5. **Assign + merge**: assigns each word to a speaker, merges consecutive segments from same speaker

Word-level alignment before speaker assignment is far more accurate than segment-level embedding
clustering (the old approach produced 100+ spurious clusters on long audio).

Output format with diarization:
```
[00:03:50 -> 00:04:00] SPEAKER_00: 你要不要来回应一下 就是好多人就会好奇
[00:04:02 -> 00:06:01] SPEAKER_01: 就不透露 不透露公司的情况 但是就 还是挺有趣的...
```

## HuggingFace Token Notes

- The token must belong to the account that accepted the model licenses
- Verify token validity: `curl -H "Authorization: Bearer <token>" https://huggingface.co/pyannote/speaker-diarization-community-1/resolve/main/config.yaml` should return HTTP 200
- If you get 403, the token is either invalid or the license hasn't been accepted for the correct model (`speaker-diarization-community-1`, not `speaker-diarization-3.1`)

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
- With `--diarize`: each line prefixed with `[HH:MM:SS -> HH:MM:SS] SPEAKER_XX:`

## Notes

- **GPU required**: The script checks for CUDA GPU at startup and exits immediately if unavailable (no CPU fallback)
- **Multi-GPU**: Automatically uses all available GPUs by default; splits audio and transcribes in parallel via `spawn` subprocesses
- **Dedicated env**: Always use `/gluster_osa_cv/user/jinzili/env/whisperx` — whisperx needs transformers 4.x which conflicts with the base env's transformers 5.x
- **pyannote model**: Use `speaker-diarization-community-1` (not `speaker-diarization-3.1`) — whisperx 3.8 defaults to community-1
- **torchcodec warning**: A `UserWarning` about torchcodec appears on every run — this is harmless, whisperx uses soundfile for audio loading
- Bilibili URL query parameters (e.g., `?spm_id_from=...`) are safely ignored
- For multi-part videos (分P), use `--playlist-items` to select specific parts
- Chinese characters in filenames are preserved correctly
- No Bilibili login required for public videos; for members-only content use `--cookies`
- VAD (Voice Activity Detection) is enabled by default to skip silence and improve speed
- First run downloads the Whisper model (~3 GB for large-v3); subsequent runs use cached model
