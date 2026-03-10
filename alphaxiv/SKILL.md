---
name: alphaxiv
description: Fetch trending and top-liked AI/ML research papers from alphaxiv.org with pagination (Load more) support. Use when the user asks about trending papers on alphaxiv, popular ML/AI research, hot arxiv papers, most-liked/viewed papers, or wants to browse/search recent research from alphaxiv.org. NOT for: Hugging Face papers (use hf-papers), general arxiv search, or paper PDF downloads.
---

# AlphaXiv Paper Fetcher

Fetch trending papers from [alphaxiv.org](https://www.alphaxiv.org/) via its public REST API, with full pagination (Load more) support.

## Quick Start

```bash
python3 scripts/fetch_papers.py --sort Hot --limit 10
python3 scripts/fetch_papers.py --sort Views --interval "7 Days"
python3 scripts/fetch_papers.py --pages 3   # Load 3 pages (60 papers)
```

## API Details

Endpoint: `GET https://api.alphaxiv.org/papers/v3/feed`

Query parameters:
- `pageNum`: 0-indexed page number
- `pageSize`: fixed 20 per page
- `sort`: `Hot` | `Comments` | `Views` | `Likes` | `GitHub` | `Twitter (X)` | `Recommended`
- `interval`: `3 Days` | `7 Days` | `30 Days` | `90 Days` | `All time`
- `topics`: JSON array of arXiv categories, e.g. `["cs.AI","cs.CL"]`
- `organizations`: JSON array, e.g. `["Google"]`

No authentication required.

## Script Usage

`scripts/fetch_papers.py` — standalone, no dependencies beyond Python 3 stdlib.

```
python3 scripts/fetch_papers.py [OPTIONS]

Options:
  --sort, -s SORT          Hot (default), Comments, Views, Likes, GitHub, Twitter (X)
  --interval, -i INTERVAL  3 Days, 7 Days, 30 Days, 90 Days, All time (default)
  --topics, -t TOPICS      arXiv categories to filter (e.g. cs.AI cs.CL)
  --pages, -p N            Number of pages to load, 20 papers/page (default: 1)
  --limit, -n N            Max papers to return
  --format, -f FORMAT      text (default), json, md
  --output, -o FILE        Save to file (default: stdout)
```

### Output Formats

- **text**: Human-readable with views, votes, authors, summary, topics, links
- **json**: Structured JSON with full metadata for downstream processing
- **md**: Markdown with abstracts in collapsible details

### Output Fields

Each paper includes: title, abstract, AI summary, key insights, authors, organizations, topics, views (all + 7d), votes, GitHub stars/URL, arXiv URL, AlphaXiv URL, publication date.

## Common Tasks

### Browse hot papers
```bash
python3 scripts/fetch_papers.py --limit 10
```

### Papers trending this week
```bash
python3 scripts/fetch_papers.py --interval "7 Days" --sort Hot
```

### Most viewed papers of all time
```bash
python3 scripts/fetch_papers.py --sort Views --pages 3
```

### GitHub-popular papers
```bash
python3 scripts/fetch_papers.py --sort GitHub --limit 10
```

### Filter by topic
```bash
python3 scripts/fetch_papers.py --topics cs.AI cs.CL --limit 20
```

### Load more (pagination)
Each page returns 20 papers. Use `--pages N` to load multiple pages:
```bash
python3 scripts/fetch_papers.py --pages 5              # 100 papers
python3 scripts/fetch_papers.py --pages 5 --limit 50   # cap at 50
```

### Export for downstream processing
```bash
python3 scripts/fetch_papers.py --format json -o trending.json
python3 scripts/fetch_papers.py --format md -o papers.md
```
