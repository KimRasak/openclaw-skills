#!/usr/bin/env python3
"""One-shot script: download Bilibili audio via yt-dlp, then transcribe with faster-whisper.

Usage:
  python bilibili_transcribe.py <URL> [OPTIONS]

Examples:
  # Firstly, make sure you logged in to huggingface.

  # Basic (auto-detect language, diarization on, all GPUs):
  python bilibili_transcribe.py "https://www.bilibili.com/video/BV1dKPrzPEwc/"

  # Chinese, 2 speakers, timestamps, output to specific dir:
  python bilibili_transcribe.py "https://www.bilibili.com/video/BV1dKPrzPEwc/" \
      -o output/ -l zh --num-speakers 2 --timestamps

  # No diarization, 1 GPU:
  python bilibili_transcribe.py "https://www.bilibili.com/video/BV1dKPrzPEwc/" \
      --no-diarize --num-gpus 1
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WHISPERX_PYTHON = "/gluster_osa_cv/user/jinzili/env/whisperx/bin/python3"
TRANSCRIBE_SCRIPT = Path(__file__).parent / "transcribe_audio.py"


def find_yt_dlp() -> str:
    """Return path to yt-dlp executable, or exit if not found."""
    for candidate in ["yt-dlp", str(Path(sys.executable).parent / "yt-dlp")]:
        result = subprocess.run(["which", candidate], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    print("Error: yt-dlp not found. Install with: pip install yt-dlp", file=sys.stderr)
    sys.exit(1)


def download_audio(url: str, output_dir: Path, yt_dlp: str) -> Path:
    """Download audio from URL using yt-dlp. Returns path to downloaded mp3."""
    output_dir.mkdir(parents=True, exist_ok=True)
    template = str(output_dir / "%(title)s.%(ext)s")

    print(f"\n[1/2] Downloading audio from: {url}")
    cmd = [
        yt_dlp,
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--print", "after_move:filepath",   # print final path after conversion
        "-o", template,
        url,
    ]
    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode != 0:
        print(f"Error: yt-dlp failed (exit {result.returncode})", file=sys.stderr)
        sys.exit(1)

    # Locate the downloaded mp3 in output_dir
    mp3_files = sorted(output_dir.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not mp3_files:
        print("Error: No mp3 file found after yt-dlp download.", file=sys.stderr)
        sys.exit(1)
    audio_path = mp3_files[0]
    print(f"    Audio saved: {audio_path}")
    return audio_path


def transcribe(audio_path: Path, output_txt: Path, args: argparse.Namespace) -> None:
    """Call transcribe_audio.py via whisperx python env."""
    print(f"\n[2/2] Transcribing: {audio_path}")

    cmd = [
        WHISPERX_PYTHON,
        str(TRANSCRIBE_SCRIPT),
        str(audio_path),
        "-o", str(output_txt),
        "-m", args.model,
        "--beam-size", str(args.beam_size),
        "--num-gpus", str(args.num_gpus),
    ]

    if args.language:
        cmd += ["-l", args.language]
    if args.timestamps:
        cmd.append("--timestamps")
    if not args.no_diarize:
        cmd.append("--diarize")
        if args.num_speakers:
            cmd += ["--num-speakers", str(args.num_speakers)]
        if args.hf_token:
            cmd += ["--hf-token", args.hf_token]

    env = os.environ.copy()
    if args.hf_token:
        env["HF_TOKEN"] = args.hf_token

    result = subprocess.run(cmd, env=env)
    if result.returncode != 0:
        print(f"Error: transcription failed (exit {result.returncode})", file=sys.stderr)
        sys.exit(1)

    print(f"\nDone! Transcript saved to: {output_txt}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Bilibili audio and transcribe to text in one step.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("url", help="Bilibili video URL")
    parser.add_argument(
        "-o", "--output", default="output",
        help="Output directory (default: output/). Audio and txt are saved here.",
    )
    parser.add_argument("-l", "--language", default=None,
                        help="Language hint for Whisper (e.g. zh, en, ja). Default: auto-detect.")
    parser.add_argument("-m", "--model", default="large-v3",
                        choices=["tiny", "base", "small", "medium", "large-v3"],
                        help="Whisper model size (default: large-v3)")
    parser.add_argument("--beam-size", type=int, default=5, help="Beam search width (default: 5)")
    parser.add_argument("--timestamps", action="store_true",
                        help="Include [HH:MM:SS -> HH:MM:SS] timestamps in output")
    parser.add_argument("--no-diarize", action="store_true",
                        help="Disable speaker diarization (diarization is ON by default)")
    parser.add_argument("--num-speakers", type=int, default=None,
                        help="Expected number of speakers (improves diarization accuracy)")
    parser.add_argument("--hf-token", default=os.environ.get("HF_TOKEN"),
                        help="HuggingFace token for pyannote (default: $HF_TOKEN env var)")
    parser.add_argument("--num-gpus", type=int, default=0,
                        help="Number of GPUs for transcription (default: 0 = all available)")
    args = parser.parse_args()

    output_dir = Path(args.output)
    yt_dlp = find_yt_dlp()

    # Step 1: download
    audio_path = download_audio(args.url, output_dir, yt_dlp)

    # Step 2: transcribe — output txt next to audio with same stem
    output_txt = audio_path.with_suffix(".txt")
    transcribe(audio_path, output_txt, args)


if __name__ == "__main__":
    main()
