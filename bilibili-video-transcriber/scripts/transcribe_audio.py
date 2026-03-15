#!/usr/bin/env python3
"""Transcribe audio files to text using faster-whisper (GPU), with optional speaker diarization
and multi-GPU parallel transcription.

Diarization mode uses WhisperX pipeline:
  transcribe → word-align → pyannote diarize → assign speakers
which gives word-level boundary accuracy instead of segment-level clustering.
"""

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


OVERLAP_MS = 10_000  # 10s overlap between adjacent chunks


def split_audio(
    audio_path: str, num_chunks: int, tmp_dir: str,
) -> list[tuple[str, float, float]]:
    """Split audio into N chunks with overlapping windows.

    Returns [(chunk_path, offset_seconds, boundary_seconds), ...] where
    boundary_seconds is the original (non-overlapping) start of the *next* chunk,
    used later to deduplicate segments in the overlap region.
    """
    from pydub import AudioSegment

    print(f"Splitting audio into {num_chunks} chunks (overlap={OVERLAP_MS}ms) ...")
    audio = AudioSegment.from_file(audio_path)
    total_ms = len(audio)
    stride_ms = total_ms // num_chunks
    chunks: list[tuple[str, float, float]] = []
    for i in range(num_chunks):
        start_ms = max(0, i * stride_ms - OVERLAP_MS) if i > 0 else 0
        end_ms = total_ms if i == num_chunks - 1 else (i + 1) * stride_ms
        boundary = (i + 1) * stride_ms / 1000.0 if i < num_chunks - 1 else total_ms / 1000.0
        chunk = audio[start_ms:end_ms]
        chunk_path = os.path.join(tmp_dir, f"chunk_{i:03d}.mp3")
        chunk.export(chunk_path, format="mp3")
        chunks.append((chunk_path, start_ms / 1000.0, boundary))
    print(f"Split complete: {num_chunks} chunks, total {total_ms / 1000:.1f}s")
    return chunks


def _worker_transcribe(
    chunk_path: str,
    offset: float,
    gpu_id: int,
    model_size: str,
    language: str | None,
    beam_size: int,
    use_whisperx: bool = False,
) -> list[dict]:
    """Worker function: transcribe one chunk on a specific GPU. Runs in a subprocess."""
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
    if use_whisperx:
        import whisperx
        model = whisperx.load_model(model_size, "cuda", compute_type="float16", language=language)
        audio = whisperx.load_audio(chunk_path)
        result = model.transcribe(audio, batch_size=16, language=language)
        segments = []
        for seg in result["segments"]:
            segments.append({
                "start": seg["start"] + offset,
                "end": seg["end"] + offset,
                "text": seg["text"].strip(),
            })
    else:
        model = WhisperModel(model_size, device="cuda", compute_type="float16")
        raw_segments, info = model.transcribe(
            chunk_path,
            language=language,
            beam_size=beam_size,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )
        segments = []
        for seg in raw_segments:
            segments.append({
                "start": seg.start + offset,
                "end": seg.end + offset,
                "text": seg.text.strip(),
            })
    print(f"  GPU {gpu_id}: {len(segments)} segments from {format_timestamp(offset)}")
    return segments


def _deduplicate_overlap(all_segments: list[list[dict]], boundaries: list[float]) -> list[dict]:
    """Merge per-chunk segment lists, dropping duplicates in overlap regions.

    For each pair of adjacent chunks, segments from the earlier chunk that extend
    past the boundary are dropped in favour of the later chunk's segments that
    start near the boundary. This keeps the version with more surrounding context.
    """
    merged: list[dict] = []
    for i, segs in enumerate(all_segments):
        if i < len(boundaries):
            boundary = boundaries[i]
            # Keep segments whose midpoint is before the boundary
            segs = [s for s in segs if (s["start"] + s["end"]) / 2 < boundary]
        if i > 0 and boundaries:
            prev_boundary = boundaries[i - 1]
            # Drop segments whose midpoint is before the previous boundary
            segs = [s for s in segs if (s["start"] + s["end"]) / 2 >= prev_boundary]
        merged.extend(segs)
    merged.sort(key=lambda s: s["start"])
    return merged


def parallel_transcribe(
    audio_path: str,
    num_gpus: int,
    model_size: str = "large-v3",
    language: str | None = None,
    beam_size: int = 5,
    use_whisperx: bool = False,
) -> list[dict]:
    """Split audio across GPUs with overlap, transcribe in parallel, merge and deduplicate."""
    ctx = multiprocessing.get_context("spawn")
    with tempfile.TemporaryDirectory(prefix="whisper_parallel_") as tmp_dir:
        chunks = split_audio(audio_path, num_gpus, tmp_dir)
        print(f"Launching {num_gpus} parallel transcription workers ...")
        t0 = time.time()

        all_segments: list[list[dict]] = [[] for _ in range(num_gpus)]
        boundaries = [boundary for _, _, boundary in chunks[:-1]]

        with ProcessPoolExecutor(max_workers=num_gpus, mp_context=ctx) as executor:
            future_to_idx = {}
            for i, (chunk_path, offset, _boundary) in enumerate(chunks):
                fut = executor.submit(
                    _worker_transcribe,
                    chunk_path, offset, i, model_size, language, beam_size, use_whisperx,
                )
                future_to_idx[fut] = i

            for fut in as_completed(future_to_idx):
                idx = future_to_idx[fut]
                all_segments[idx] = fut.result()

        merged = _deduplicate_overlap(all_segments, boundaries)

        elapsed = time.time() - t0
        print(f"Parallel transcription complete: {len(merged)} segments in {elapsed:.1f}s "
              f"({num_gpus} GPUs)")
        return merged


def whisperx_diarize(
    audio_path: str,
    model_size: str = "large-v3",
    language: str | None = None,
    beam_size: int = 5,
    num_speakers: int | None = None,
    hf_token: str | None = None,
    num_gpus: int = 1,
) -> list[dict]:
    """Transcribe and diarize using WhisperX pipeline with multi-GPU parallel transcription.

    Steps:
      1. Split audio into num_gpus chunks, transcribe in parallel (one GPU each)
      2. Merge + deduplicate overlap regions → full segment list
      3. Align to word-level timestamps on GPU 0 (full audio)
      4. Run pyannote speaker diarization on GPU 0 (full audio, global speaker embedding)
      5. Assign each word to a speaker, group into segments
    """
    import whisperx

    device = "cuda"

    token = hf_token or os.environ.get("HF_TOKEN")
    if not token:
        print(
            "Error: --diarize requires a HuggingFace token.\n"
            "  Set HF_TOKEN env var or pass --hf-token <token>\n"
            "  Also accept model licenses at:\n"
            "    https://huggingface.co/pyannote/speaker-diarization-community-1\n"
            "    https://huggingface.co/pyannote/segmentation-3.0",
            file=sys.stderr,
        )
        sys.exit(1)

    # Step 1: Multi-GPU parallel transcription
    if num_gpus > 1:
        print(f"[WhisperX] Transcribing with {num_gpus} GPUs in parallel ...")
        segments_raw = parallel_transcribe(
            audio_path, num_gpus, model_size, language, beam_size, use_whisperx=True,
        )
        # Reconstruct whisperx result format for alignment
        result = {"segments": [{"start": s["start"], "end": s["end"], "text": s["text"]}
                                for s in segments_raw],
                  "language": language or "zh"}
    else:
        os.environ["CUDA_VISIBLE_DEVICES"] = "0"
        print(f"[WhisperX] Loading model '{model_size}' ...")
        model = whisperx.load_model(model_size, device, compute_type="float16", language=language)
        audio_array = whisperx.load_audio(audio_path)
        print(f"[WhisperX] Transcribing ...")
        t0 = time.time()
        result = model.transcribe(audio_array, batch_size=16, language=language)
        print(f"[WhisperX] Transcription done in {time.time() - t0:.1f}s, "
              f"{len(result['segments'])} segments")
        del model

    detected_lang = result.get("language", language or "zh")

    # Load full audio for alignment and diarization (runs on GPU 0)
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"
    audio_array = whisperx.load_audio(audio_path)

    # Step 2: Word-level alignment
    print(f"[WhisperX] Loading alignment model for language '{detected_lang}' ...")
    model_a, metadata = whisperx.load_align_model(language_code=detected_lang, device=device)
    result = whisperx.align(
        result["segments"], model_a, metadata, audio_array, device,
        return_char_alignments=False,
    )
    print(f"[WhisperX] Alignment done")
    del model_a

    # Step 3: Speaker diarization on full audio
    print(f"[WhisperX] Running speaker diarization ...")
    t0 = time.time()
    from whisperx.diarize import DiarizationPipeline, assign_word_speakers
    diarize_model = DiarizationPipeline(token=token, device=device)
    kwargs = {}
    if num_speakers:
        kwargs["min_speakers"] = num_speakers
        kwargs["max_speakers"] = num_speakers
    diarize_segments = diarize_model(audio_array, **kwargs)
    print(f"[WhisperX] Diarization done in {time.time() - t0:.1f}s")

    # Step 4: Assign speakers to words, then to segments
    result = assign_word_speakers(diarize_segments, result)

    segments = []
    for seg in result["segments"]:
        segments.append({
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"].strip(),
            "speaker": seg.get("speaker", "UNKNOWN"),
        })

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
    hf_token: str | None = None,
):
    available_gpus = require_gpu()

    audio = Path(audio_path)
    if not audio.exists():
        print(f"Error: audio file not found: {audio}", file=sys.stderr)
        sys.exit(1)

    if output_path is None:
        output_path = str(audio.with_suffix(".txt"))

    if diarize:
        use_gpus = min(num_gpus or available_gpus, available_gpus)
        print(f"Diarization mode: WhisperX pipeline (transcribe x{use_gpus} GPUs → align → diarize)")
        segments = whisperx_diarize(
            str(audio),
            model_size=model_size,
            language=language,
            beam_size=beam_size,
            num_speakers=num_speakers,
            hf_token=hf_token,
            num_gpus=use_gpus,
        )
        segments = merge_consecutive(segments)
    else:
        # Plain transcription: faster-whisper, multi-GPU parallel if available
        use_gpus = min(num_gpus or available_gpus, available_gpus)
        if use_gpus > 1:
            print(f"Using {use_gpus}/{available_gpus} GPUs for parallel transcription")
            segments = parallel_transcribe(str(audio), use_gpus, model_size, language, beam_size)
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
    parser.add_argument("--diarize", action="store_true",
                        help="Enable speaker diarization via WhisperX + pyannote (requires HF_TOKEN)")
    parser.add_argument("--num-speakers", type=int, default=None,
                        help="Number of speakers (improves diarization accuracy when known)")
    parser.add_argument("--hf-token", default=None,
                        help="HuggingFace token for pyannote models (or set HF_TOKEN env var)")
    parser.add_argument("--num-gpus", type=int, default=None,
                        help="Number of GPUs for parallel transcription (default: all available). "
                             "In --diarize mode, transcription is parallelized; align+diarize always run on GPU 0.")
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
        hf_token=args.hf_token,
    )


if __name__ == "__main__":
    main()
