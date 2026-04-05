#!/usr/bin/env python3
"""Download videos from Douyin (抖音) share links.

Parses the obfuscated share text to extract the short URL, resolves it,
fetches video metadata, and downloads the watermark-free video.

Usage:
  python douyin_download.py <SHARE_TEXT_OR_URL> [OPTIONS]

Examples:
  python douyin_download.py "7.08 February/ February复制打开抖音，看看【xxx】的作品 https://v.douyin.com/aBcDeFg/"
  python douyin_download.py "https://v.douyin.com/aBcDeFg/" -o my_videos/
"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

try:
    import requests
except ImportError:
    print("Error: requests not found. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)

# Mobile UA to mimic app share link opening
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.6 Mobile/15E148 Safari/604.1"
)

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Patterns for extracting short URLs from share text
SHORT_URL_PATTERNS = [
    r'(https?://v\.douyin\.com/[A-Za-z0-9_\-]+/?)',
    r'(https?://www\.iesdouyin\.com/share/video/\d+/?)',
]


def extract_url(text: str) -> str:
    """Extract a Douyin short URL from share text or return the URL directly."""
    text = text.strip()
    # If it's already a full douyin.com video URL, return as-is
    if re.match(r'https?://(www\.)?douyin\.com/video/\d+', text):
        return text
    # Try to find a short URL in the text
    for pattern in SHORT_URL_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    # Maybe the user passed a bare URL without https
    if 'v.douyin.com' in text:
        match = re.search(r'(v\.douyin\.com/[A-Za-z0-9_\-]+/?)', text)
        if match:
            return 'https://' + match.group(1)
    print(f"Error: Could not find a Douyin URL in the input text.", file=sys.stderr)
    sys.exit(1)


def resolve_short_url(short_url: str) -> str:
    """Follow redirects on a short URL to get the final video page URL."""
    print(f"Resolving short URL: {short_url}")
    session = requests.Session()
    session.headers.update({"User-Agent": MOBILE_UA})
    resp = session.get(short_url, allow_redirects=True, timeout=15)
    final_url = resp.url
    print(f"Resolved to: {final_url}")

    # Detect failed redirects that land on the homepage instead of a video page
    parsed = urlparse(final_url)
    stripped = f"{parsed.scheme}://{parsed.netloc}"
    if parsed.hostname and parsed.hostname.lstrip("www.") == "douyin.com" and not re.search(r'/video/|/note/|modal_id=', final_url):
        print(
            f"Error: Short URL redirected to homepage ({final_url}) instead of a video page.\n"
            f"This usually means the link has expired or the network blocked the redirect.",
            file=sys.stderr,
        )
        sys.exit(1)

    return final_url


def extract_video_id(url: str) -> str:
    """Extract the numeric video ID from a Douyin URL."""
    # Try /video/{id} pattern
    match = re.search(r'/video/(\d+)', url)
    if match:
        return match.group(1)
    # Try modal_id parameter
    match = re.search(r'modal_id=(\d+)', url)
    if match:
        return match.group(1)
    # Try note/{id} pattern (for image posts, but may contain video)
    match = re.search(r'/note/(\d+)', url)
    if match:
        return match.group(1)
    print(
        f"Error: Could not extract video ID from URL: {url}\n"
        f"The URL does not contain a /video/{{id}}, modal_id=, or /note/{{id}} pattern.",
        file=sys.stderr,
    )
    sys.exit(1)


def fetch_video_info(video_id: str) -> dict:
    """Fetch video metadata from Douyin using multiple fallback methods."""
    print(f"Fetching video info for ID: {video_id}")

    session = requests.Session()
    session.headers.update({
        "User-Agent": MOBILE_UA,
        "Referer": "https://www.douyin.com/",
    })

    # Method 1: Parse _ROUTER_DATA from iesdouyin share page
    try:
        share_url = f"https://www.iesdouyin.com/share/video/{video_id}/"
        resp = session.get(share_url, timeout=15)
        match = re.search(
            r'window\._ROUTER_DATA\s*=\s*(\{.+?\})\s*</script>',
            resp.text, re.DOTALL,
        )
        if match:
            router_data = json.loads(match.group(1))
            loader = router_data.get("loaderData", {})
            for key, val in loader.items():
                if isinstance(val, dict):
                    items = (val.get("videoInfoRes") or {}).get("item_list")
                    if items:
                        return items[0]
    except Exception as e:
        print(f"iesdouyin _ROUTER_DATA method failed: {e}, trying API...", file=sys.stderr)

    # Method 2: Try the legacy web API (may return empty on some networks)
    try:
        api = f"https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids={video_id}"
        resp = session.get(api, timeout=15)
        if resp.status_code == 200 and resp.text.strip():
            data = resp.json()
            items = data.get("item_list", [])
            if items:
                return items[0]
    except Exception as e:
        print(f"API method failed: {e}, trying page parse...", file=sys.stderr)

    # Method 3: Parse RENDER_DATA from douyin.com video page
    try:
        page_url = f"https://www.douyin.com/video/{video_id}"
        session.headers["User-Agent"] = DESKTOP_UA
        resp = session.get(page_url, timeout=15)
        match = re.search(
            r'<script id="RENDER_DATA"[^>]*>(.*?)</script>',
            resp.text, re.DOTALL,
        )
        if match:
            raw = unquote(match.group(1))
            render_data = json.loads(raw)
            for key, val in render_data.items():
                if isinstance(val, dict):
                    detail = val.get("aweme", {}).get("detail", {})
                    if detail:
                        return detail
    except Exception as e:
        print(f"Page parse method failed: {e}", file=sys.stderr)

    print("Error: Could not fetch video info via any method.", file=sys.stderr)
    sys.exit(1)


def get_video_url(info: dict) -> tuple[str, str]:
    """Extract the best video download URL and title from video info.

    Returns (video_url, title).
    """
    title = info.get("desc", "") or info.get("aweme_id", "douyin_video")
    # Clean title for filename
    title = re.sub(r'[\\/:*?"<>|\n\r]', '_', title).strip()[:120]
    if not title:
        title = "douyin_video"

    # Try to get watermark-free URL
    video = info.get("video", {})

    # play_addr is the standard field
    play_addr = video.get("play_addr", {})
    url_list = play_addr.get("url_list", [])

    # bit_rate contains higher quality options (may be None)
    bit_rate = video.get("bit_rate") or []
    if bit_rate:
        # Sort by bitrate descending, pick the best
        bit_rate.sort(key=lambda x: x.get("bit_rate", 0), reverse=True)
        best = bit_rate[0]
        br_urls = best.get("play_addr", {}).get("url_list", [])
        if br_urls:
            url_list = br_urls

    if not url_list:
        print("Error: No video URL found in metadata.", file=sys.stderr)
        sys.exit(1)

    # Pick the first available URL and remove watermark
    video_url = url_list[0]
    # Replace watermarked endpoint with clean one
    video_url = video_url.replace("playwm", "play")

    return video_url, title


def download_video(video_url: str, title: str, output_dir: Path) -> Path:
    """Download the video file to output_dir. Returns the saved file path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{title}.mp4"

    print(f"Downloading video: {title}")
    print(f"URL: {video_url[:80]}...")

    headers = {
        "User-Agent": MOBILE_UA,
        "Referer": "https://www.douyin.com/",
    }
    resp = requests.get(video_url, headers=headers, stream=True, timeout=60)
    resp.raise_for_status()

    total = int(resp.headers.get("Content-Length", 0))
    downloaded = 0
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = downloaded * 100 // total
                print(f"\r  Progress: {pct}% ({downloaded // 1024}KB / {total // 1024}KB)", end="", flush=True)
    print()  # newline after progress

    print(f"Video saved: {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download videos from Douyin (抖音) share links.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("text", help="Douyin share text or URL")
    parser.add_argument("-o", "--output", default="output",
                        help="Output directory (default: output/)")
    parser.add_argument("--info-only", action="store_true",
                        help="Only print video info and download URL, don't download")
    args = parser.parse_args()

    # Step 1: Extract URL from share text
    url = extract_url(args.text)
    print(f"Extracted URL: {url}")

    # Step 2: Resolve short URL to full URL (if needed)
    if 'v.douyin.com' in url or 'iesdouyin.com' in url:
        url = resolve_short_url(url)

    # Step 3: Extract video ID
    video_id = extract_video_id(url)
    print(f"Video ID: {video_id}")

    # Step 4: Fetch video metadata
    info = fetch_video_info(video_id)

    # Step 5: Get download URL
    video_url, title = get_video_url(info)
    print(f"Title: {title}")
    print(f"Download URL: {video_url[:100]}...")

    if args.info_only:
        print(f"\nFull download URL:\n{video_url}")
        return

    # Step 6: Download
    video_path = download_video(video_url, title, Path(args.output))
    print(f"\nDone! Downloaded: {video_path}")


if __name__ == "__main__":
    main()
