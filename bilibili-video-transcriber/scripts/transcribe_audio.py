#!/usr/bin/env python3
"""Transcribe audio files to text using faster-whisper (CTranslate2) on GPU."""

import argparse
import os
import sys
import time


def transcribe(
    audio_path: str,
    output_path: str | None = None,
    model_size: str = "large-v3",
    language: str | None = None,
    device: str = "cuda",
    compute_type: str = "float16",
    beam_size: int = 5,
    with_timestamps: bool = False,
):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("Error: faster-whisper not installed. Run: pip install faster-whisper")
        sys.exit(1)

    if not os.path.isfile(audio_path):
        print(f"Error: audio file not found: {audio_path}")
        sys.exit(1)

    print(f"Loading model: {model_size} (device={device}, compute_type={compute_type})")
    t0 = time.time()
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    print(f"Model loaded in {time.time() - t0:.1f}s")

    print(f"Transcribing: {audio_path}")
    t0 = time.time()
    segments, info = model.transcribe(
        audio_path,
        beam_size=beam_size,
        language=language,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )

    lines = []
    for seg in segments:
        if with_timestamps:
            lines.append(f"[{_fmt(seg.start)} -> {_fmt(seg.end)}] {seg.text.strip()}")
        else:
            lines.append(seg.text.strip())

    elapsed = time.time() - t0
    text = "\n".join(lines)

    if output_path is None:
        base = os.path.splitext(audio_path)[0]
        output_path = base + ".txt"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"Done in {elapsed:.1f}s  |  language={info.language} (prob={info.language_probability:.2f})")
    print(f"Saved to: {output_path}  ({len(lines)} segments, {len(text)} chars)")
    return output_path


def _fmt(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def main():
    parser = argparse.ArgumentParser(
        description="Transcribe audio to text using faster-whisper on GPU"
    )
    parser.add_argument("audio", help="Path to the audio file (mp3/wav/m4a/flac/...)")
    parser.add_argument("-o", "--output", default=None, help="Output text file path (default: same name as audio with .txt)")
    parser.add_argument("-m", "--model", default="large-v3", help="Whisper model size: tiny/base/small/medium/large-v3 (default: large-v3)")
    parser.add_argument("-l", "--language", default=None, help="Language code, e.g. zh/en/ja (default: auto-detect)")
    parser.add_argument("--device", default="cuda", help="Device: cuda or cpu (default: cuda)")
    parser.add_argument("--compute-type", default="float16", help="Compute type: float16/int8/int8_float16 (default: float16)")
    parser.add_argument("--beam-size", type=int, default=5, help="Beam size (default: 5)")
    parser.add_argument("--timestamps", action="store_true", help="Include timestamps in output")
    args = parser.parse_args()

    transcribe(
        audio_path=args.audio,
        output_path=args.output,
        model_size=args.model,
        language=args.language,
        device=args.device,
        compute_type=args.compute_type,
        beam_size=args.beam_size,
        with_timestamps=args.timestamps,
    )


if __name__ == "__main__":
    main()
