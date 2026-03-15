#!/usr/bin/env python3
"""Transcribe audio files to text using faster-whisper (GPU), with optional speaker diarization
and multi-GPU parallel transcription."""

import argparse
import multiprocessing
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from faster_whisper import WhisperModel


def require_gpu() -> int:
    """Check GPU availability without initializing CUDA in the main process
    (to avoid poisoning forked subprocesses). Uses nvidia-smi instead."""
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,name,memory.total", "--format=csv,noheader,nounits"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("Error: CUDA GPU not available. This script requires a GPU to run.", file=sys.stderr)
        sys.exit(1)
    lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
    if not lines:
        print("Error: No GPUs detected.", file=sys.stderr)
        sys.exit(1)
    for line in lines:
        idx, name, mem_mb = [x.strip() for x in line.split(",")]
        print(f"  GPU {idx}: {name} ({int(mem_mb) / 1024:.1f} GB)")
    return len(lines)


def format_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def split_audio(audio_path: str, num_chunks: int, tmp_dir: str) -> list[tuple[str, float]]:
    """Split audio into N chunks, return [(chunk_path, offset_seconds), ...]."""
    from pydub import AudioSegment

    print(f"Splitting audio into {num_chunks} chunks ...")
    audio = AudioSegment.from_file(audio_path)
    total_ms = len(audio)
    chunk_ms = total_ms // num_chunks
    chunks: list[tuple[str, float]] = []
    for i in range(num_chunks):
        start_ms = i * chunk_ms
        end_ms = total_ms if i == num_chunks - 1 else (i + 1) * chunk_ms
        chunk = audio[start_ms:end_ms]
        chunk_path = os.path.join(tmp_dir, f"chunk_{i:03d}.mp3")
        chunk.export(chunk_path, format="mp3")
        chunks.append((chunk_path, start_ms / 1000.0))
    print(f"Split complete: {num_chunks} chunks, total {total_ms / 1000:.1f}s")
    return chunks


def _worker_transcribe(
    chunk_path: str,
    offset: float,
    gpu_id: int,
    model_size: str,
    language: str | None,
    beam_size: int,
) -> list[dict]:
    """Worker function: transcribe one chunk on a specific GPU. Runs in a subprocess."""
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
    model = WhisperModel(model_size, device="cuda", compute_type="float16")
    segments, info = model.transcribe(
        chunk_path,
        language=language,
        beam_size=beam_size,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )
    result = []
    for seg in segments:
        result.append({
            "start": seg.start + offset,
            "end": seg.end + offset,
            "text": seg.text.strip(),
        })
    print(f"  GPU {gpu_id}: {len(result)} segments from {format_timestamp(offset)}")
    return result


def parallel_transcribe(
    audio_path: str,
    num_gpus: int,
    model_size: str = "large-v3",
    language: str | None = None,
    beam_size: int = 5,
) -> tuple[list[dict], str | None]:
    """Split audio across GPUs, transcribe in parallel, merge results."""
    ctx = multiprocessing.get_context("spawn")
    with tempfile.TemporaryDirectory(prefix="whisper_parallel_") as tmp_dir:
        chunks = split_audio(audio_path, num_gpus, tmp_dir)
        print(f"Launching {num_gpus} parallel transcription workers ...")
        t0 = time.time()

        all_segments: list[list[dict]] = [[] for _ in range(num_gpus)]

        with ProcessPoolExecutor(max_workers=num_gpus, mp_context=ctx) as executor:
            future_to_idx = {}
            for i, (chunk_path, offset) in enumerate(chunks):
                fut = executor.submit(
                    _worker_transcribe,
                    chunk_path, offset, i, model_size, language, beam_size,
                )
                future_to_idx[fut] = i

            for fut in as_completed(future_to_idx):
                idx = future_to_idx[fut]
                all_segments[idx] = fut.result()

        merged = []
        for segs in all_segments:
            merged.extend(segs)

        elapsed = time.time() - t0
        print(f"Parallel transcription complete: {len(merged)} segments in {elapsed:.1f}s "
              f"({num_gpus} GPUs)")
        return merged, None


def _get_hf_token() -> str | None:
    """Read HuggingFace token from env var or cached token file."""
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if token:
        return token
    token_path = Path.home() / ".cache" / "huggingface" / "token"
    if token_path.exists():
        return token_path.read_text().strip() or None
    return None


def diarize_audio(
    audio_path: str,
    num_speakers: int | None = None,
) -> list[tuple[float, float, str]]:
    """Run pyannote speaker diarization pipeline, return [(start, end, speaker), ...]."""
    import torch
    from pyannote.audio import Pipeline

    hf_token = _get_hf_token()
    if not hf_token:
        print("Error: HuggingFace token required for pyannote speaker diarization.\n"
              "Set HF_TOKEN env var or run: huggingface-cli login\n"
              "Also accept the model license at: https://huggingface.co/pyannote/speaker-diarization-3.1",
              file=sys.stderr)
        sys.exit(1)

    print("Loading speaker diarization pipeline ...")
    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=hf_token)
    pipeline.to(torch.device("cuda"))

    print("Running speaker diarization ...")
    kwargs = {}
    if num_speakers is not None:
        kwargs["num_speakers"] = num_speakers
    diarization = pipeline(audio_path, **kwargs)

    turns: list[tuple[float, float, str]] = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        turns.append((turn.start, turn.end, speaker))
    print(f"Diarization complete: {len(turns)} turns, "
          f"{len({s for _, _, s in turns})} speakers detected")
    return turns


def assign_speakers(
    segments: list[dict],
    diar_turns: list[tuple[float, float, str]],
) -> list[dict]:
    """Assign a speaker label to each transcript segment by max time overlap."""
    for seg in segments:
        seg_start, seg_end = seg["start"], seg["end"]
        best_speaker = "UNKNOWN"
        best_overlap = 0.0
        for turn_start, turn_end, speaker in diar_turns:
            overlap = max(0.0, min(seg_end, turn_end) - max(seg_start, turn_start))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = speaker
        seg["speaker"] = best_speaker
    return segments


def merge_consecutive(segments: list[dict]) -> list[dict]:
    """Merge consecutive segments from the same speaker into one."""
    if not segments:
        return segments
    merged: list[dict] = [segments[0].copy()]
    for seg in segments[1:]:
        prev = merged[-1]
        if seg.get("speaker") == prev.get("speaker"):
            prev["end"] = seg["end"]
            prev["text"] = prev["text"] + " " + seg["text"]
        else:
            merged.append(seg.copy())
    return merged


def transcribe(
    audio_path: str,
    output_path: str | None = None,
    model_size: str = "large-v3",
    language: str | None = None,
    beam_size: int = 5,
    timestamps: bool = False,
    diarize: bool = False,
    num_speakers: int | None = None,
    num_gpus: int | None = None,
):
    available_gpus = require_gpu()

    audio = Path(audio_path)
    if not audio.exists():
        print(f"Error: audio file not found: {audio}", file=sys.stderr)
        sys.exit(1)

    if output_path is None:
        output_path = str(audio.with_suffix(".txt"))

    use_gpus = min(num_gpus or available_gpus, available_gpus)

    if use_gpus > 1:
        print(f"Using {use_gpus}/{available_gpus} GPUs for parallel transcription")
        segments, _ = parallel_transcribe(
            str(audio), use_gpus, model_size, language, beam_size,
        )
    else:
        device = "cuda"
        compute_type = "float16"
        print(f"Loading model '{model_size}' on {device} ({compute_type}) ...")
        model = WhisperModel(model_size, device=device, compute_type=compute_type)

        print(f"Transcribing: {audio_path}")
        raw_segments, info = model.transcribe(
            str(audio),
            language=language,
            beam_size=beam_size,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        if info.language:
            print(f"Detected language: {info.language} (prob={info.language_probability:.2f})")

        segments = [
            {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
            for seg in raw_segments
        ]
        print(f"Transcription complete: {len(segments)} segments")

    if diarize:
        diar_turns = diarize_audio(str(audio), num_speakers=num_speakers)
        segments = assign_speakers(segments, diar_turns)
        segments = merge_consecutive(segments)

    lines: list[str] = []
    for seg in segments:
        parts: list[str] = []
        if timestamps or diarize:
            parts.append(f"[{format_timestamp(seg['start'])} -> {format_timestamp(seg['end'])}]")
        if diarize:
            parts.append(f"{seg.get('speaker', 'UNKNOWN')}:")
        parts.append(seg["text"])
        lines.append(" ".join(parts))

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
    parser.add_argument("--diarize", action="store_true", help="Enable speaker diarization (requires pyannote.audio)")
    parser.add_argument("--num-speakers", type=int, default=None, help="Number of speakers (improves diarization accuracy)")
    parser.add_argument("--num-gpus", type=int, default=None,
                        help="Number of GPUs for parallel transcription (default: all available)")
    args = parser.parse_args()

    transcribe(
        audio_path=args.audio,
        output_path=args.output,
        model_size=args.model,
        language=args.language,
        beam_size=args.beam_size,
        timestamps=args.timestamps,
        diarize=args.diarize,
        num_speakers=args.num_speakers,
        num_gpus=args.num_gpus,
    )


if __name__ == "__main__":
    main()
