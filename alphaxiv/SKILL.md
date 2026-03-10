---
name: alphaxiv
description: Fetch trending and top-liked AI/ML research papers from alphaxiv.org. Use when the user asks about trending papers on alphaxiv, popular ML/AI research, hot arxiv papers, most-liked papers, or wants to browse/search recent research from alphaxiv.org. NOT for: Hugging Face papers (use hf-papers), general arxiv search, or paper PDF downloads.
---

# AlphaXiv Paper Fetcher

Fetch trending and most-liked papers from [alphaxiv.org](https://www.alphaxiv.org/) via its internal REST API.

## Quick Start

```bash
python3 scripts/fetch_papers.py --sort Hot --limit 10
python3 scripts/fetch_papers.py --sort Likes --limit 10
```

## API Details

Endpoint: `GET https://api.alphaxiv.org/papers/v3/feed`

Key query parameters:
- `sort`: `Hot` (recent trending), `Likes` (all-time most liked), `New`
- `interval`: `All time`, `Past week`, `Past month`, `Past year`
- `pageNum`: 0-indexed page number
- `pageSize`: max 20

The API returns full paper metadata including title, abstract, AI-generated summary, authors, organizations, arxiv ID, votes, visits, GitHub URL/stars, and publication date.

## Script Usage

`scripts/fetch_papers.py` — standalone, no dependencies beyond Python 3 stdlib.

```
python3 scripts/fetch_papers.py [OPTIONS]

Options:
  --sort SORT        Hot (default), Likes, New
  --interval TEXT    "All time" (default), "Past week", "Past month", "Past year"
  --page N           Page number, 0-indexed (default: 0)
  --limit N          Papers per page, max 20 (default: 20)
  --format FORMAT    table (default), json, brief
  --query TEXT       Client-side keyword filter on title/abstract
```

### Output Formats

- **table**: Human-readable table with rank, votes, visits, date, title, orgs, arxiv ID
- **json**: Structured JSON with title, arxiv_id, votes, visits, pub_date, authors, orgs, summary, github_url, github_stars
- **brief**: One-liner per paper: `1. [248👍] Title (arxiv_id)`

## Common Tasks

### Compare Hot vs Most Liked
Run the script twice with `--sort Hot` and `--sort Likes`. Hot reflects recent trending; Likes is cumulative all-time. They typically have zero overlap.

### Search for a topic
Use `--query "attention"` to client-side filter results by keyword in title or abstract.

### Get full metadata for downstream processing
Use `--format json` and pipe to `jq` or parse in Python.

### Paginate
Use `--page 0`, `--page 1`, etc. Each page returns up to 20 papers.
