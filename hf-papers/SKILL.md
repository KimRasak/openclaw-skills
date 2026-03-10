---
name: hf-papers
description: Fetch and display Hugging Face Daily/Weekly/Monthly papers. Use when the user asks about trending AI/ML papers, Hugging Face papers, arxiv daily digests, or wants to browse/search recent research papers from huggingface.co/papers.
---

# HF Papers

Fetch papers from Hugging Face Daily Papers via `scripts/hf_papers.py`.

## Quick Reference

```bash
# Today's papers (default)
python3 scripts/hf_papers.py

# Specific date
python3 scripts/hf_papers.py -d 2026-03-03

# Weekly / Monthly aggregation
python3 scripts/hf_papers.py -p week
python3 scripts/hf_papers.py -p month

# Sort by upvotes / date / comments
python3 scripts/hf_papers.py -p week --sort upvotes

# Limit results
python3 scripts/hf_papers.py -n 10

# Fetch ALL pages (week/month may exceed 100)
python3 scripts/hf_papers.py -p month --all

# Output formats: text (default) / json / md
python3 scripts/hf_papers.py -f json -o papers.json
python3 scripts/hf_papers.py -f md -o papers.md
```

## Parameters

| Flag | Short | Description | Default |
|------|-------|-------------|---------|
| `--date` | `-d` | Date (YYYY-MM-DD) | today |
| `--period` | `-p` | `day` / `week` / `month` | `day` |
| `--limit` | `-n` | Max papers to return | 50 |
| `--all` | `-a` | Fetch all pages | off |
| `--format` | `-f` | `text` / `json` / `md` | `text` |
| `--output` | `-o` | Save to file | stdout |
| `--sort` | | `upvotes` / `date` / `comments` | API order |

## Output Fields

Each paper includes: title, authors, organization, upvotes, comments, AI summary, keywords, arxiv URL, GitHub repo (with stars), and project page.

## Usage Notes

- API limit per request: 100. Use `--all` for full week/month lists.
- Script uses only Python stdlib (no pip dependencies).
- Status messages go to stderr; paper output goes to stdout.
- For user-facing summaries, prefer `text` format. For downstream processing, use `json`.
