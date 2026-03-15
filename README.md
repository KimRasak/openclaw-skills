# OpenClaw Skills

AI 研究助理技能集合 —— 用于论文发现、文献追踪和研究话题探索。

可配合 [OpenClaw](https://github.com/openclaw-ai) Agent 或 Cursor/Claude 等 AI 编辑器使用。

## Skills 一览

| Skill | 用途 | 数据源 | 需要 API Key |
|-------|------|--------|:---:|
| [alphaxiv](alphaxiv/) | 获取热门/高赞 AI/ML 论文，支持分页 | [alphaxiv.org](https://www.alphaxiv.org/) | 否 |
| [hf-papers](hf-papers/) | 获取 Hugging Face 每日/每周/每月论文 | [huggingface.co/papers](https://huggingface.co/papers) | 否 |
| [citation-explorer](citation-explorer/) | 从种子论文出发，沿引用链发散探索研究话题，生成话题关系图谱 | [OpenAlex API](https://openalex.org/) (2.5亿+ 文献) | 否 |
| [bilibili-video-transcriber](bilibili-video-transcriber/) | 下载B站视频音频并用 Whisper 转录为文本，支持多GPU并行和说话人分离 | [Bilibili](https://www.bilibili.com/) + [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (GPU) + [pyannote.audio](https://github.com/pyannote/pyannote-audio) | 说话人分离需HF Token |

## 快速使用

### alphaxiv — 热门论文

```bash
python3 alphaxiv/scripts/fetch_papers.py --sort Hot --limit 10
python3 alphaxiv/scripts/fetch_papers.py --sort Views --interval "7 Days"
```

### hf-papers — HuggingFace 每日论文

```bash
python3 hf-papers/scripts/hf_papers.py              # 今日论文
python3 hf-papers/scripts/hf_papers.py --date 2026-03-10  # 指定日期
```

### citation-explorer — 研究话题发散探索

```bash
# 搜索种子论文
python3 citation-explorer/scripts/scholar-search.py search "qwen vision language" --limit 5

# 以种子论文为中心，发散探索相关研究话题，生成可视化图谱
python3 citation-explorer/scripts/citation-explorer.py explore \
  --seed "10.48550/arXiv.2308.12966" \
  --depth 2 --max-papers 30 --strategy priority \
  --focus image vision generation multimodal \
  --exclude-topics medical healthcare biology \
  --render-graph topic_map.html
```

### bilibili-video-transcriber — B站视频转文字

```bash
# 1. 下载音频
yt-dlp -x --audio-format mp3 --audio-quality 0 \
  -o "output/%(title)s.%(ext)s" \
  "https://www.bilibili.com/video/BV1xxxxxxxxx/"

# 2. 多GPU 并行转录 + 说话人分离
python3 bilibili-video-transcriber/scripts/transcribe_audio.py "output/视频标题.mp3" \
  -o "output/视频标题.txt" -l zh --diarize --num-gpus 4
```

## 目录结构

```
openclaw-skills/
├── alphaxiv/
│   ├── SKILL.md
│   └── scripts/fetch_papers.py
├── hf-papers/
│   ├── SKILL.md
│   └── scripts/hf_papers.py
├── citation-explorer/
│   ├── SKILL.md
│   └── scripts/
│       ├── scholar-search.py       # OpenAlex 论文搜索
│       ├── citation-explorer.py    # 引用链发散探索引擎
│       └── render-graph.py         # 研究话题图谱渲染 (D3.js)
├── bilibili-video-transcriber/
│   ├── SKILL.md
│   └── scripts/
│       └── transcribe_audio.py     # faster-whisper GPU 音频转文字
└── README.md
```

## 安装方式

每个 Skill 都是独立的，直接复制对应目录到你的 AI 工具的 skills 路径即可：

```bash
# Cursor
cp -r citation-explorer/ ~/.cursor/skills/citation-explorer/

# Claude Code
cp -r citation-explorer/ ~/.claude/skills/citation-explorer/

# OpenClaw Agent
python3 scripts/skill_manager.py add-remote \
  --agent zhongshu --name citation_explorer \
  --source https://raw.githubusercontent.com/KimRasak/openclaw-skills/main/citation-explorer/SKILL.md
```

所有 Skill 均无需 API Key。大部分零外部依赖（仅 Python 标准库），`bilibili-video-transcriber` 需要 `yt-dlp`、`ffmpeg` 和 `faster-whisper`。
