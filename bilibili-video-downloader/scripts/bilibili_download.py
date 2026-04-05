#!/usr/bin/env python3
"""Download audio from Bilibili videos using yt-dlp.

Usage:
  python bilibili_download.py <URL> [OPTIONS]

Examples:
  python bilibili_download.py "https://www.bilibili.com/video/BV1dKPrzPEwc/"
  python bilibili_download.py "https://www.bilibili.com/video/BV1dKPrzPEwc/" -o my_audio/ --audio-format flac
"""

import argparse
import subprocess
import sys
from pathlib import Path


def find_yt_dlp() -> str:
    """Return path to yt-dlp executable, or exit if not found."""
    for candidate in ["yt-dlp", str(Path(sys.executable).parent / "yt-dlp")]:
        result = subprocess.run(["which", candidate], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    print("Error: yt-dlp not found. Install with: pip install yt-dlp", file=sys.stderr)
    sys.exit(1)


def download_audio(url: str, output_dir: Path, yt_dlp: str,
                   audio_format: str = "mp3", audio_quality: int = 0,
                   cookies: str | None = None,
                   playlist_items: str | None = None) -> Path:
    """Download audio from URL using yt-dlp. Returns path to downloaded file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    template = str(output_dir / "%(title)s.%(ext)s")

    print(f"Downloading audio from: {url}")
    cmd = [
        yt_dlp,
        "-x",
        "--audio-format", audio_format,
        "--audio-quality", str(audio_quality),
        "--print", "after_move:filepath",
        "-o", template,
    ]
    if cookies:
        cmd += ["--cookies", cookies]
    if playlist_items:
        cmd += ["--playlist-items", playlist_items]
    cmd.append(url)

    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode != 0:
        print(f"Error: yt-dlp failed (exit {result.returncode})", file=sys.stderr)
        sys.exit(1)

    # Locate the downloaded file in output_dir
    audio_files = sorted(
        output_dir.glob(f"*.{audio_format}"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if not audio_files:
        print(f"Error: No {audio_format} file found after download.", file=sys.stderr)
        sys.exit(1)
    audio_path = audio_files[0]
    print(f"Audio saved: {audio_path}")
    return audio_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download audio from Bilibili videos using yt-dlp.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("url", help="Bilibili video URL")
    parser.add_argument("-o", "--output", default="output",
                        help="Output directory (default: output/)")
    parser.add_argument("--audio-format", default="mp3",
                        choices=["mp3", "aac", "flac", "m4a", "opus", "wav"],
                        help="Audio format (default: mp3)")
    parser.add_argument("--audio-quality", type=int, default=0,
                        help="Audio quality 0-10, 0=best (default: 0)")
    parser.add_argument("--cookies", default=None,
                        help="Path to cookies file (for members-only content)")
    parser.add_argument("--playlist-items", default=None,
                        help="Playlist items to download (e.g. '1-3', '2')")
    args = parser.parse_args()

    yt_dlp = find_yt_dlp()
    audio_path = download_audio(
        url=args.url,
        output_dir=Path(args.output),
        yt_dlp=yt_dlp,
        audio_format=args.audio_format,
        audio_quality=args.audio_quality,
        cookies=args.cookies,
        playlist_items=args.playlist_items,
    )
    print(f"\nDone! Downloaded: {audio_path}")


if __name__ == "__main__":
    main()
