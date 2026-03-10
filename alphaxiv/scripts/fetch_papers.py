#!/usr/bin/env python3
"""Fetch trending papers from alphaxiv.org via its internal API.

Usage:
    python3 fetch_papers.py [OPTIONS]

Options:
    --sort SORT        Sorting mode: Hot (default), Likes, New
    --interval INTERVAL Time range: "All time" (default), "Past week", "Past month", "Past year"
    --page PAGE        Page number, 0-indexed (default: 0)
    --limit LIMIT      Papers per page, max 20 (default: 20)
    --format FORMAT    Output format: table (default), json, brief
    --query QUERY      Filter results by keyword in title (client-side)

Examples:
    python3 fetch_papers.py
    python3 fetch_papers.py --sort Likes --limit 10
    python3 fetch_papers.py --sort Hot --interval "Past week" --format json
    python3 fetch_papers.py --query "attention" --format brief
"""

import argparse
import json
import sys
import urllib.request
import urllib.parse
import urllib.error

API_BASE = "https://api.alphaxiv.org/papers/v3/feed"


def fetch_papers(sort="Hot", interval="All time", page=0, limit=20):
    params = urllib.parse.urlencode({
        "pageNum": page,
        "sort": sort,
        "pageSize": min(limit, 20),
        "interval": interval,
    })
    url = f"{API_BASE}?{params}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"Error: HTTP {e.code} from API", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    return data.get("papers", [])


def filter_papers(papers, query):
    if not query:
        return papers
    q = query.lower()
    return [p for p in papers if q in p.get("title", "").lower()
            or q in p.get("abstract", "").lower()]


def format_table(papers):
    lines = []
    lines.append(f"{'#':>3}  {'👍':>5}  {'👀':>7}  {'Date':10}  Title")
    lines.append("-" * 90)
    for i, p in enumerate(papers, 1):
        m = p.get("metrics", {})
        votes = m.get("public_total_votes", 0)
        visits = m.get("visits_count", {}).get("all", 0)
        date = p.get("first_publication_date", "")[:10]
        title = p["title"]
        if len(title) > 65:
            title = title[:62] + "..."
        orgs = [o["name"] for o in p.get("organization_info", [])[:2]]
        org_str = f" ({', '.join(orgs)})" if orgs else ""
        arxiv = p.get("universal_paper_id", "")
        lines.append(f"{i:3}  {votes:5}  {visits:7}  {date}  {title}{org_str} [{arxiv}]")
    return "\n".join(lines)


def format_brief(papers):
    lines = []
    for i, p in enumerate(papers, 1):
        m = p.get("metrics", {})
        votes = m.get("public_total_votes", 0)
        arxiv = p.get("universal_paper_id", "")
        lines.append(f"{i}. [{votes}👍] {p['title']} ({arxiv})")
    return "\n".join(lines)


def format_json(papers):
    compact = []
    for p in papers:
        m = p.get("metrics", {})
        compact.append({
            "title": p["title"],
            "arxiv_id": p.get("universal_paper_id"),
            "votes": m.get("public_total_votes", 0),
            "visits": m.get("visits_count", {}).get("all", 0),
            "pub_date": p.get("first_publication_date", "")[:10],
            "authors": [a["full_name"] for a in p.get("full_authors", [])[:5]],
            "orgs": [o["name"] for o in p.get("organization_info", [])],
            "summary": (p.get("paper_summary", {}) or {}).get("summary", ""),
            "github_url": p.get("github_url"),
            "github_stars": p.get("github_stars"),
        })
    return json.dumps(compact, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description="Fetch alphaxiv trending papers")
    parser.add_argument("--sort", default="Hot", help="Hot, Likes, or New")
    parser.add_argument("--interval", default="All time",
                        help="All time, Past week, Past month, Past year")
    parser.add_argument("--page", type=int, default=0)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--format", default="table", choices=["table", "json", "brief"])
    parser.add_argument("--query", default="", help="Filter by keyword in title/abstract")
    args = parser.parse_args()

    papers = fetch_papers(args.sort, args.interval, args.page, args.limit)
    papers = filter_papers(papers, args.query)

    if not papers:
        print("No papers found.", file=sys.stderr)
        sys.exit(0)

    if args.format == "json":
        print(format_json(papers))
    elif args.format == "brief":
        print(format_brief(papers))
    else:
        print(format_table(papers))


if __name__ == "__main__":
    main()
