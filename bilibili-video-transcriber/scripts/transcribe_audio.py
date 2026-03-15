#!/usr/bin/env python3
"""Transcribe audio files to text using faster-whisper (GPU)."""

import argparse
import sys
from pathlib import Path

import torch
from faster_whisper import WhisperModel


def require_gpu():
    if not torch.cuda.is_available():
        print("Error: CUDA GPU not available. This script requires a GPU to run.", file=sys.stderr)
        sys.exit(1)
    gpu_name = torch.cuda.get_device_name(0)
    gpu_mem = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
    print(f"GPU: {gpu_name} ({gpu_mem:.1f} GB)")


def format_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def transcribe(
    audio_path: str,
    output_path: str | None = None,
    model_size: str = "large-v3",
    language: str | None = None,
    beam_size: int = 5,
    timestamps: bool = False,
):
    require_gpu()

    audio = Path(audio_path)
    if not audio.exists():
        print(f"Error: audio file not found: {audio}", file=sys.stderr)
        sys.exit(1)

    if output_path is None:
        output_path = str(audio.with_suffix(".txt"))

    device = "cuda"
    compute_type = "float16"
    print(f"Loading model '{model_size}' on {device} ({compute_type}) ...")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    print(f"Transcribing: {audio_path}")
    segments, info = model.transcribe(
        str(audio),
        language=language,
        beam_size=beam_size,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )

    if info.language:
        print(f"Detected language: {info.language} (prob={info.language_probability:.2f})")

    lines: list[str] = []
    for seg in segments:
        if timestamps:
            prefix = f"[{format_timestamp(seg.start)} -> {format_timestamp(seg.end)}] "
        else:
            prefix = ""
        lines.append(f"{prefix}{seg.text.strip()}")

    text = "\n".join(lines)
    Path(output_path).write_text(text, encoding="utf-8")
    print(f"Saved transcript ({len(lines)} segments) to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Transcribe audio to text with faster-whisper")
    parser.add_argument("audio", help="Path to audio file")
    parser.add_argument("-o", "--output", default=None, help="Output text file path")
    parser.add_argument("-m", "--model", default="large-v3", help="Model size (default: large-v3)")
    parser.add_argument("-l", "--language", default=None, help="Language code (e.g. zh, en, ja)")
    parser.add_argument("--beam-size", type=int, default=5, help="Beam search width")
    parser.add_argument("--timestamps", action="store_true", help="Include timestamps")
    args = parser.parse_args()

    transcribe(
        audio_path=args.audio,
        output_path=args.output,
        model_size=args.model,
        language=args.language,
        beam_size=args.beam_size,
        timestamps=args.timestamps,
    )


if __name__ == "__main__":
    main()
