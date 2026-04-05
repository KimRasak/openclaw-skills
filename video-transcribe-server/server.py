#!/usr/bin/env python3
"""Video Transcribe Server

A web server that accepts Douyin/Bilibili share links, downloads the video,
and transcribes the audio to text using a resident whisper model on a specified CUDA GPU.

Usage:
    CUDA_VISIBLE_DEVICES=0 /gluster_osa_cv/user/jinzili/env/whisperx/bin/python3 server.py \
        --port 7860 --model large-v3

The whisper model stays loaded in GPU memory between requests for fast turnaround.
"""

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

# ---------------------------------------------------------------------------
# Paths to sibling skill scripts (relative to this repo)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DOUYIN_SCRIPT = REPO_ROOT / "douyin-video-downloader" / "scripts" / "douyin_download.py"
BILIBILI_SCRIPT = REPO_ROOT / "bilibili-video-downloader" / "scripts" / "bilibili_download.py"

# ---------------------------------------------------------------------------
# Link detection
# ---------------------------------------------------------------------------
DOUYIN_PATTERNS = [
    re.compile(r'https?://v\.douyin\.com/[A-Za-z0-9_\-]+/?'),
    re.compile(r'https?://(www\.)?douyin\.com/video/\d+'),
    re.compile(r'https?://www\.iesdouyin\.com/share/video/\d+/?'),
    re.compile(r'v\.douyin\.com/[A-Za-z0-9_\-]+/?'),
]

BILIBILI_PATTERNS = [
    re.compile(r'https?://(www\.)?bilibili\.com/video/BV\w+'),
    re.compile(r'https?://b23\.tv/\w+'),
    re.compile(r'b23\.tv/\w+'),
    re.compile(r'BV[A-Za-z0-9]{10}'),
]


def detect_source(text: str) -> str:
    """Return 'douyin', 'bilibili', or 'unknown'."""
    for pat in DOUYIN_PATTERNS:
        if pat.search(text):
            return "douyin"
    for pat in BILIBILI_PATTERNS:
        if pat.search(text):
            return "bilibili"
    return "unknown"


# ---------------------------------------------------------------------------
# Download helpers (call sibling scripts as subprocesses)
# ---------------------------------------------------------------------------
def _extract_bilibili_url(share_text: str) -> str:
    """Extract a usable Bilibili URL from share text or raw URL."""
    url_match = re.search(r'(https?://\S+)', share_text)
    if url_match:
        return url_match.group(1)
    bv_match = re.search(r'(BV[A-Za-z0-9]{10})', share_text)
    if bv_match:
        return f"https://www.bilibili.com/video/{bv_match.group(1)}/"
    b23_match = re.search(r'(b23\.tv/\w+)', share_text)
    if b23_match:
        return f"https://{b23_match.group(1)}"
    return share_text.strip()


def download_douyin(share_text: str, output_dir: Path) -> Path:
    """Download a Douyin video. Returns path to the downloaded .mp4 file."""
    cmd = [
        sys.executable, str(DOUYIN_SCRIPT),
        share_text,
        "-o", str(output_dir),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise RuntimeError("抖音下载超时 (120s)")

    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        combined = stderr or stdout or ""
        lines = combined.splitlines()
        error_lines = [l for l in lines if l.startswith("Error:")]
        detail = "\n".join(error_lines) if error_lines else (stderr or stdout or "(无输出)")

        if "redirected to homepage" in combined or "Could not extract video ID" in combined:
            raise RuntimeError(
                "抖音下载失败: 链接已失效或网络被拦截，短链接跳转到了抖音首页而非视频页面。请重新复制分享链接后重试。"
            )
        raise RuntimeError(f"抖音下载失败: {detail}")

    mp4_files = sorted(output_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not mp4_files:
        raise RuntimeError("抖音下载后未找到 .mp4 文件")
    return mp4_files[0]


def download_bilibili(share_text: str, output_dir: Path) -> Path:
    """Download audio from a Bilibili video. Returns path to the downloaded audio file."""
    url = _extract_bilibili_url(share_text)

    cmd = [
        sys.executable, str(BILIBILI_SCRIPT),
        url,
        "-o", str(output_dir),
        "--audio-format", "mp3",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        raise RuntimeError("B站下载超时 (300s)")

    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        lines = (stderr or stdout or "").splitlines()
        error_lines = [l for l in lines if "error" in l.lower() or "Error" in l]
        detail = "\n".join(error_lines) if error_lines else (stderr or stdout or "(无输出)")
        raise RuntimeError(f"B站下载失败: {detail}")

    audio_files = sorted(output_dir.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not audio_files:
        raise RuntimeError("B站下载后未找到 .mp3 文件")
    return audio_files[0]


# ---------------------------------------------------------------------------
# Transcription (in-process, using resident model)
# ---------------------------------------------------------------------------
class TranscriberModel:
    """Keeps a whisper model loaded in GPU memory."""

    def __init__(self, model_size: str = "large-v3"):
        from faster_whisper import WhisperModel
        print(f"[TranscriberModel] Loading '{model_size}' on CUDA (float16) ...")
        t0 = time.time()
        self.model = WhisperModel(model_size, device="cuda", compute_type="float16")
        self.model_size = model_size
        print(f"[TranscriberModel] Model loaded in {time.time() - t0:.1f}s")

    def transcribe(
        self, audio_path: str, language: str | None = None, beam_size: int = 5,
    ) -> list[dict]:
        raw_segments, info = self.model.transcribe(
            audio_path,
            language=language,
            beam_size=beam_size,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )
        detected = ""
        if info.language:
            detected = info.language
            print(f"  Detected language: {info.language} (prob={info.language_probability:.2f})")

        segments = []
        for seg in raw_segments:
            text = seg.text.strip()
            if text:
                segments.append({
                    "start": seg.start,
                    "end": seg.end,
                    "text": text,
                })
        return segments


def format_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def segments_to_text(segments: list[dict], timestamps: bool = True) -> str:
    lines = []
    for seg in segments:
        if timestamps:
            prefix = f"[{format_timestamp(seg['start'])} -> {format_timestamp(seg['end'])}] "
        else:
            prefix = ""
        lines.append(f"{prefix}{seg['text']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Async-safe WebSocket send helper
# ---------------------------------------------------------------------------
async def ws_send_safe(websocket: WebSocket, data: dict) -> bool:
    """Send JSON to websocket, return False if connection is gone."""
    try:
        await websocket.send_json(data)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Video Transcribe Server")
transcriber: TranscriberModel | None = None
_transcribe_lock = asyncio.Lock()


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>视频转录服务</title>
<style>
  :root {
    --bg: #0b0d11;
    --surface: #151820;
    --surface-hover: #1c2030;
    --border: #252836;
    --border-focus: #6c63ff;
    --primary: #6c63ff;
    --primary-hover: #5a52e0;
    --primary-glow: rgba(108, 99, 255, 0.15);
    --text: #e8e8ed;
    --text-muted: #7c7f8a;
    --text-dim: #55586a;
    --success: #34d399;
    --error: #f87171;
    --warning: #fbbf24;
    --douyin-color: #fe2c55;
    --bilibili-color: #00a1d6;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: var(--text-dim); }

  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC",
                 "PingFang SC", "Microsoft YaHei", sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    display: flex;
    justify-content: center;
    padding-top: 6vh;
  }

  .container {
    width: 100%;
    max-width: 720px;
    padding: 0 1.5rem 4rem;
  }

  /* ---- Header ---- */
  .header { margin-bottom: 2.5rem; }
  .header h1 {
    font-size: 1.5rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    margin-bottom: 0.4rem;
  }
  .header p {
    color: var(--text-muted);
    font-size: 0.88rem;
    line-height: 1.5;
  }

  /* ---- Card ---- */
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 1.5rem;
    margin-bottom: 1.25rem;
    transition: border-color 0.2s;
  }
  .card:focus-within { border-color: var(--border-focus); }

  textarea {
    width: 100%;
    min-height: 110px;
    padding: 0;
    background: transparent;
    border: none;
    color: var(--text);
    font-size: 0.93rem;
    line-height: 1.7;
    resize: vertical;
    outline: none;
    font-family: inherit;
  }
  textarea::placeholder { color: var(--text-dim); }

  .card-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 1rem;
    padding-top: 0.85rem;
    border-top: 1px solid var(--border);
  }

  .options {
    display: flex;
    gap: 1rem;
    align-items: center;
  }

  .option-label {
    font-size: 0.82rem;
    color: var(--text-muted);
    display: flex;
    align-items: center;
    gap: 0.35rem;
    cursor: pointer;
    user-select: none;
  }

  .option-label input[type="checkbox"] {
    accent-color: var(--primary);
    width: 15px;
    height: 15px;
    cursor: pointer;
  }

  .btn {
    padding: 0.6rem 1.8rem;
    background: var(--primary);
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 0.88rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s, box-shadow 0.15s, opacity 0.15s;
    white-space: nowrap;
  }
  .btn:hover:not(:disabled) {
    background: var(--primary-hover);
    box-shadow: 0 0 20px var(--primary-glow);
  }
  .btn:disabled { opacity: 0.4; cursor: not-allowed; }

  /* ---- Steps progress ---- */
  .steps {
    display: none;
    gap: 0;
    margin-bottom: 1.25rem;
  }
  .steps.visible { display: flex; }

  .step {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    position: relative;
  }

  .step-dot {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: var(--surface);
    border: 2px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.72rem;
    font-weight: 700;
    color: var(--text-dim);
    z-index: 1;
    transition: all 0.3s;
  }

  .step.active .step-dot {
    border-color: var(--primary);
    color: var(--primary);
    box-shadow: 0 0 12px var(--primary-glow);
  }
  .step.done .step-dot {
    border-color: var(--success);
    background: var(--success);
    color: var(--bg);
  }
  .step.error .step-dot {
    border-color: var(--error);
    background: var(--error);
    color: white;
  }

  .step-label {
    margin-top: 0.45rem;
    font-size: 0.72rem;
    color: var(--text-dim);
    transition: color 0.3s;
  }
  .step.active .step-label { color: var(--text); }
  .step.done .step-label { color: var(--success); }
  .step.error .step-label { color: var(--error); }

  .step-line {
    position: absolute;
    top: 14px;
    left: calc(50% + 18px);
    right: calc(-50% + 18px);
    height: 2px;
    background: var(--border);
    transition: background 0.3s;
  }
  .step.done .step-line { background: var(--success); }
  .step:last-child .step-line { display: none; }

  /* ---- Source tag ---- */
  .source-tag {
    display: none;
    align-items: center;
    gap: 0.35rem;
    padding: 0.3rem 0.7rem;
    border-radius: 6px;
    font-size: 0.78rem;
    font-weight: 600;
    margin-bottom: 1.25rem;
  }
  .source-tag.visible { display: inline-flex; }
  .source-tag.douyin { background: rgba(254,44,85,0.12); color: var(--douyin-color); }
  .source-tag.bilibili { background: rgba(0,161,214,0.12); color: var(--bilibili-color); }

  /* ---- Log panel ---- */
  .log-panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
    display: none;
    margin-bottom: 1.25rem;
  }
  .log-panel.visible { display: block; }

  .log-header {
    padding: 0.65rem 1rem;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--text-muted);
  }

  .log-timer {
    font-variant-numeric: tabular-nums;
    color: var(--text-dim);
    font-weight: 500;
  }

  .log-body {
    padding: 0.85rem 1rem;
    max-height: 180px;
    overflow-y: auto;
    font-family: "JetBrains Mono", "Fira Code", "SF Mono", monospace;
    font-size: 0.78rem;
    line-height: 1.7;
    color: var(--text-muted);
    white-space: pre-wrap;
    word-wrap: break-word;
  }
  .log-body .log-error { color: var(--error); }

  /* ---- Result panel ---- */
  .result-panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
    display: none;
  }
  .result-panel.visible { display: block; }

  .result-header {
    padding: 0.65rem 1rem;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .result-title {
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--text-muted);
  }

  .result-meta {
    font-size: 0.72rem;
    color: var(--text-dim);
    font-weight: 400;
    margin-left: 0.5rem;
  }

  .result-actions { display: flex; gap: 0.4rem; }

  .btn-sm {
    padding: 0.28rem 0.65rem;
    font-size: 0.75rem;
    border-radius: 6px;
    background: var(--border);
    color: var(--text-muted);
    border: none;
    cursor: pointer;
    transition: all 0.15s;
    font-weight: 500;
  }
  .btn-sm:hover { background: var(--primary); color: white; }
  .btn-sm.copied { background: var(--success); color: var(--bg); }

  .result-body {
    padding: 1rem;
    max-height: 480px;
    overflow-y: auto;
    font-size: 0.88rem;
    line-height: 1.85;
    white-space: pre-wrap;
    word-wrap: break-word;
    color: var(--text);
  }

  /* ---- Status badge ---- */
  .status-line {
    display: none;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 1.25rem;
    font-size: 0.82rem;
  }
  .status-line.visible { display: flex; }

  .spinner {
    width: 16px; height: 16px;
    border: 2px solid var(--border);
    border-top-color: var(--primary);
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    flex-shrink: 0;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  .status-text { color: var(--text-muted); }
  .status-text.done { color: var(--success); }
  .status-text.error { color: var(--error); }

  /* ---- Footer ---- */
  .footer {
    margin-top: 3rem;
    text-align: center;
    color: var(--text-dim);
    font-size: 0.72rem;
  }

  /* ---- Responsive ---- */
  @media (max-width: 540px) {
    body { padding-top: 3vh; }
    .container { padding: 0 1rem 3rem; }
    .card { padding: 1.1rem; }
    .header h1 { font-size: 1.25rem; }
    .step-label { font-size: 0.65rem; }
  }
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <h1>视频转录服务</h1>
    <p>粘贴抖音 / B站的分享链接，自动下载并转录为文字</p>
  </div>

  <div class="card" id="inputCard">
    <textarea id="inputText"
      placeholder="在此粘贴分享链接或分享文字...&#10;&#10;支持：&#10;  抖音 — 复制打开抖音...https://v.douyin.com/xxx/&#10;  B 站 — https://www.bilibili.com/video/BVxxx/"></textarea>
    <div class="card-footer">
      <div class="options">
        <label class="option-label">
          <input type="checkbox" id="optTimestamps" checked> 显示时间戳
        </label>
      </div>
      <button class="btn" id="btnSubmit" onclick="startTranscribe()">开始转录</button>
    </div>
  </div>

  <span class="source-tag" id="sourceTag"></span>

  <div class="steps" id="stepsBar">
    <div class="step" id="step-detect">
      <div class="step-line"></div>
      <div class="step-dot">1</div>
      <div class="step-label">识别来源</div>
    </div>
    <div class="step" id="step-download">
      <div class="step-line"></div>
      <div class="step-dot">2</div>
      <div class="step-label">下载视频</div>
    </div>
    <div class="step" id="step-transcribe">
      <div class="step-dot">3</div>
      <div class="step-label">语音转录</div>
    </div>
  </div>

  <div class="status-line" id="statusLine">
    <div class="spinner" id="statusSpinner"></div>
    <span class="status-text" id="statusText">处理中...</span>
  </div>

  <div class="log-panel" id="logPanel">
    <div class="log-header">
      <span>处理日志</span>
      <span class="log-timer" id="logTimer"></span>
    </div>
    <div class="log-body" id="logBody"></div>
  </div>

  <div class="result-panel" id="resultPanel">
    <div class="result-header">
      <div>
        <span class="result-title">转录结果</span>
        <span class="result-meta" id="resultMeta"></span>
      </div>
      <div class="result-actions">
        <button class="btn-sm" id="btnCopy" onclick="copyResult()">复制</button>
        <button class="btn-sm" onclick="downloadResult()">下载 .txt</button>
      </div>
    </div>
    <div class="result-body" id="resultBody"></div>
  </div>

  <div class="footer">
    Powered by faster-whisper &middot; GPU 常驻模型 &middot; 全流程过程编码
  </div>

</div>

<script>
let ws = null;
let timerHandle = null;
let startTime = null;
let segmentCount = 0;

const $ = (id) => document.getElementById(id);

function resetUI() {
  ["step-detect","step-download","step-transcribe"].forEach(id => {
    const el = $(id);
    el.classList.remove("active","done","error");
  });
  $("stepsBar").classList.remove("visible");
  $("sourceTag").classList.remove("visible","douyin","bilibili");
  $("statusLine").classList.remove("visible");
  $("logPanel").classList.remove("visible");
  $("resultPanel").classList.remove("visible");
  $("logBody").innerHTML = "";
  $("resultBody").textContent = "";
  $("resultMeta").textContent = "";
  $("statusText").className = "status-text";
  $("statusSpinner").style.display = "";
  segmentCount = 0;
}

function setStep(stepId, state) {
  const el = $(stepId);
  el.classList.remove("active","done","error");
  if (state) el.classList.add(state);
  // put checkmark for done
  const dot = el.querySelector(".step-dot");
  const num = stepId === "step-detect" ? "1" : stepId === "step-download" ? "2" : "3";
  if (state === "done") dot.textContent = "✓";
  else if (state === "error") dot.textContent = "✗";
  else dot.textContent = num;
}

function showSource(source) {
  const tag = $("sourceTag");
  tag.classList.remove("douyin","bilibili");
  if (source === "douyin") {
    tag.textContent = "抖音";
    tag.classList.add("douyin","visible");
  } else if (source === "bilibili") {
    tag.textContent = "哔哩哔哩";
    tag.classList.add("bilibili","visible");
  }
}

function setStatus(text, state) {
  $("statusLine").classList.add("visible");
  const st = $("statusText");
  st.textContent = text;
  st.className = "status-text" + (state ? " " + state : "");
  $("statusSpinner").style.display = (state === "done" || state === "error") ? "none" : "";
}

function appendLog(msg, isError) {
  const body = $("logBody");
  if (isError) {
    const span = document.createElement("span");
    span.className = "log-error";
    span.textContent = msg + "\n";
    body.appendChild(span);
  } else {
    body.appendChild(document.createTextNode(msg + "\n"));
  }
  body.scrollTop = body.scrollHeight;
}

function startTimer() {
  startTime = Date.now();
  const el = $("logTimer");
  el.textContent = "0s";
  timerHandle = setInterval(() => {
    const s = Math.floor((Date.now() - startTime) / 1000);
    const m = Math.floor(s / 60);
    el.textContent = m > 0 ? m + "m " + (s % 60) + "s" : s + "s";
  }, 500);
}

function stopTimer() {
  if (timerHandle) { clearInterval(timerHandle); timerHandle = null; }
}

function setInputEnabled(enabled) {
  $("inputText").disabled = !enabled;
  $("btnSubmit").disabled = !enabled;
  $("inputCard").style.opacity = enabled ? "1" : "0.6";
}

function startTranscribe() {
  const text = $("inputText").value.trim();
  if (!text) return;
  const timestamps = $("optTimestamps").checked;

  resetUI();
  setInputEnabled(false);
  $("stepsBar").classList.add("visible");
  $("logPanel").classList.add("visible");
  startTimer();
  setStatus("正在处理...");

  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(proto + "//" + location.host + "/ws/transcribe");

  ws.onopen = () => {
    ws.send(JSON.stringify({text, timestamps}));
  };

  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);

    if (msg.type === "step") {
      setStep(msg.id, msg.state);
      if (msg.source) showSource(msg.source);

    } else if (msg.type === "status") {
      setStatus(msg.data);

    } else if (msg.type === "log") {
      appendLog(msg.data, false);

    } else if (msg.type === "result") {
      $("resultBody").textContent = msg.data;
      $("resultMeta").textContent = msg.segments + " 段";
      $("resultPanel").classList.add("visible");
      setStatus("转录完成", "done");
      stopTimer();
      setInputEnabled(true);

    } else if (msg.type === "error") {
      appendLog(msg.data, true);
      setStatus("处理失败", "error");
      stopTimer();
      setInputEnabled(true);
    }
  };

  ws.onclose = () => {
    setInputEnabled(true);
    if ($("statusText").className === "status-text") {
      setStatus("连接已断开", "error");
      stopTimer();
    }
  };

  ws.onerror = () => {
    setStatus("WebSocket 连接失败", "error");
    stopTimer();
    setInputEnabled(true);
  };
}

function copyResult() {
  const text = $("resultBody").textContent;
  navigator.clipboard.writeText(text).then(() => {
    const btn = $("btnCopy");
    btn.textContent = "已复制";
    btn.classList.add("copied");
    setTimeout(() => { btn.textContent = "复制"; btn.classList.remove("copied"); }, 1500);
  });
}

function downloadResult() {
  const text = $("resultBody").textContent;
  const blob = new Blob([text], {type: "text/plain;charset=utf-8"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  const ts = new Date().toISOString().slice(0,19).replace(/[:T]/g, "-");
  a.download = "transcript_" + ts + ".txt";
  a.click();
  URL.revokeObjectURL(a.href);
}
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_PAGE


@app.websocket("/ws/transcribe")
async def ws_transcribe(websocket: WebSocket):
    await websocket.accept()
    try:
        raw = await websocket.receive_text()
        req = json.loads(raw)
        text = req.get("text", "").strip()
        timestamps = req.get("timestamps", True)

        if not text:
            await ws_send_safe(websocket, {"type": "error", "data": "输入不能为空"})
            return

        # --- Step 1: Detect source ---
        await ws_send_safe(websocket, {"type": "step", "id": "step-detect", "state": "active"})
        source = detect_source(text)

        if source == "unknown":
            await ws_send_safe(websocket, {"type": "step", "id": "step-detect", "state": "error"})
            await ws_send_safe(websocket, {
                "type": "error",
                "data": "无法识别链接类型，请粘贴抖音或B站的分享链接。",
            })
            return

        source_label = "抖音" if source == "douyin" else "B站"
        await ws_send_safe(websocket, {
            "type": "step", "id": "step-detect", "state": "done", "source": source,
        })
        await ws_send_safe(websocket, {
            "type": "log", "data": f"识别来源: {source_label}",
        })

        # Acquire lock so only one transcription runs at a time on the GPU
        if _transcribe_lock.locked():
            await ws_send_safe(websocket, {
                "type": "status", "data": "等待前一个任务完成...",
            })
            await ws_send_safe(websocket, {
                "type": "log", "data": "GPU 正被其他任务占用，排队等待...",
            })

        async with _transcribe_lock:
            # --- Step 2: Download ---
            await ws_send_safe(websocket, {"type": "step", "id": "step-download", "state": "active"})
            await ws_send_safe(websocket, {"type": "status", "data": f"正在下载{source_label}视频..."})
            await ws_send_safe(websocket, {"type": "log", "data": "开始下载..."})

            tmp_dir = Path(tempfile.mkdtemp(prefix="vtserver_"))
            try:
                t0 = time.time()
                loop = asyncio.get_event_loop()
                try:
                    if source == "douyin":
                        media_path = await loop.run_in_executor(
                            None, download_douyin, text, tmp_dir,
                        )
                    else:
                        media_path = await loop.run_in_executor(
                            None, download_bilibili, text, tmp_dir,
                        )
                except Exception as e:
                    await ws_send_safe(websocket, {"type": "step", "id": "step-download", "state": "error"})
                    raise

                elapsed_dl = time.time() - t0
                file_size_mb = media_path.stat().st_size / 1024 / 1024
                await ws_send_safe(websocket, {"type": "step", "id": "step-download", "state": "done"})
                await ws_send_safe(websocket, {
                    "type": "log",
                    "data": f"下载完成: {media_path.name} ({file_size_mb:.1f} MB, {elapsed_dl:.1f}s)",
                })

                # --- Step 3: Transcribe ---
                await ws_send_safe(websocket, {"type": "step", "id": "step-transcribe", "state": "active"})
                await ws_send_safe(websocket, {"type": "status", "data": "正在转录音频..."})
                await ws_send_safe(websocket, {"type": "log", "data": "开始转录..."})

                t0 = time.time()
                try:
                    segments = await loop.run_in_executor(
                        None, transcriber.transcribe, str(media_path),
                    )
                except Exception as e:
                    await ws_send_safe(websocket, {"type": "step", "id": "step-transcribe", "state": "error"})
                    raise

                elapsed_tr = time.time() - t0
                await ws_send_safe(websocket, {"type": "step", "id": "step-transcribe", "state": "done"})
                await ws_send_safe(websocket, {
                    "type": "log",
                    "data": f"转录完成: {len(segments)} 段, 耗时 {elapsed_tr:.1f}s",
                })

                result_text = segments_to_text(segments, timestamps=timestamps)
                await ws_send_safe(websocket, {
                    "type": "result", "data": result_text, "segments": len(segments),
                })

            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ws_transcribe] Error: {e}\n{tb}", file=sys.stderr)
        await ws_send_safe(websocket, {"type": "error", "data": str(e)})


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------
def _check_prerequisites():
    """Verify that sibling scripts exist before starting."""
    missing = []
    if not DOUYIN_SCRIPT.is_file():
        missing.append(str(DOUYIN_SCRIPT))
    if not BILIBILI_SCRIPT.is_file():
        missing.append(str(BILIBILI_SCRIPT))
    if missing:
        print(f"WARNING: The following sibling scripts were not found:", file=sys.stderr)
        for p in missing:
            print(f"  - {p}", file=sys.stderr)
        print("Download functionality for missing sources will fail.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Video Transcribe Server")
    parser.add_argument("--port", type=int, default=7860, help="Server port (default: 7860)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--model", default="large-v3",
                        help="Whisper model size (default: large-v3)")
    args = parser.parse_args()

    _check_prerequisites()

    global transcriber
    transcriber = TranscriberModel(model_size=args.model)

    print(f"\n{'='*40}")
    print(f"  Video Transcribe Server")
    print(f"  Model : {args.model} (resident on GPU)")
    print(f"  URL   : http://{args.host}:{args.port}")
    print(f"{'='*40}\n")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
