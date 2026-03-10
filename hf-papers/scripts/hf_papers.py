#!/usr/bin/env python3
"""
Hugging Face Daily Papers 抓取脚本

用法:
  # 抓取今日 daily papers
  python3 hf_papers.py

  # 抓取指定日期的 daily papers
  python3 hf_papers.py --date 2026-03-09

  # 抓取本周 weekly papers (按 upvotes 排序)
  python3 hf_papers.py --period week

  # 抓取本月 monthly papers
  python3 hf_papers.py --period month

  # 限制数量 (默认 50)
  python3 hf_papers.py --period week --limit 20

  # 输出为 JSON
  python3 hf_papers.py --format json

  # 输出为 Markdown 文件
  python3 hf_papers.py --format md --output papers.md

  # 同时拉取所有分页 (weekly/monthly 可能超过 100 条)
  python3 hf_papers.py --period month --all

API 文档 (逆向):
  GET https://huggingface.co/api/daily_papers
  参数:
    date       - YYYY-MM-DD, 默认今天
    periodType - day | week | month, 默认 day
    limit      - 1~100, 默认 50
    skip       - 分页偏移, 默认 0
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone, timedelta

API_BASE = "https://huggingface.co/api/daily_papers"
PAPER_URL = "https://huggingface.co/papers"
MAX_LIMIT = 100


def fetch_papers(date=None, period="day", limit=50, skip=0):
    """从 HuggingFace API 抓取论文列表"""
    params = {"periodType": period, "limit": min(limit, MAX_LIMIT), "skip": skip}
    if date:
        params["date"] = date
    url = f"{API_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "hf-papers-fetcher/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Connection Error: {e.reason}", file=sys.stderr)
        sys.exit(1)


def fetch_all_papers(date=None, period="day", limit=None):
    """分页拉取所有论文"""
    all_papers = []
    skip = 0
    batch = MAX_LIMIT
    while True:
        papers = fetch_papers(date=date, period=period, limit=batch, skip=skip)
        if not papers:
            break
        all_papers.extend(papers)
        if limit and len(all_papers) >= limit:
            all_papers = all_papers[:limit]
            break
        if len(papers) < batch:
            break
        skip += batch
    return all_papers


def parse_paper(raw):
    """解析单篇论文数据"""
    p = raw.get("paper", {})
    authors = [a["name"] for a in p.get("authors", []) if not a.get("hidden")]
    org = raw.get("organization")
    return {
        "id": p.get("id", ""),
        "title": raw.get("title", p.get("title", "")),
        "summary": raw.get("summary", p.get("summary", "")),
        "ai_summary": p.get("ai_summary", ""),
        "ai_keywords": p.get("ai_keywords", []),
        "authors": authors,
        "upvotes": p.get("upvotes", 0),
        "comments": raw.get("numComments", 0),
        "published_at": raw.get("publishedAt", p.get("publishedAt", "")),
        "submitted_at": p.get("submittedOnDailyAt", ""),
        "submitted_by": (p.get("submittedOnDailyBy") or raw.get("submittedBy") or {}).get("user", ""),
        "organization": org.get("fullname", "") if org else "",
        "thumbnail": raw.get("thumbnail", ""),
        "paper_url": f"{PAPER_URL}/{p.get('id', '')}",
        "arxiv_url": f"https://arxiv.org/abs/{p.get('id', '')}",
        "github_repo": p.get("githubRepo", ""),
        "github_stars": p.get("githubStars", 0),
        "project_page": p.get("projectPage", ""),
    }


def format_text(papers, period, date_str):
    """格式化为终端文本输出"""
    period_label = {"day": "Daily", "week": "Weekly", "month": "Monthly"}[period]
    lines = [
        f"🤗 Hugging Face {period_label} Papers — {date_str}",
        f"   共 {len(papers)} 篇",
        "=" * 70,
        "",
    ]
    for i, p in enumerate(papers, 1):
        authors_str = ", ".join(p["authors"][:3])
        if len(p["authors"]) > 3:
            authors_str += f" 等 {len(p['authors'])} 位作者"
        org_str = f" · 🏢 {p['organization']}" if p["organization"] else ""

        lines.append(f"[{i}] {p['title']}")
        lines.append(f"    ⬆️ {p['upvotes']}  💬 {p['comments']}  👤 {authors_str}{org_str}")

        if p["ai_summary"]:
            lines.append(f"    📝 {p['ai_summary']}")

        links = [f"📄 {p['paper_url']}"]
        if p["github_repo"]:
            stars = f" ⭐{p['github_stars']}" if p["github_stars"] else ""
            links.append(f"💻 {p['github_repo']}{stars}")
        if p["project_page"]:
            links.append(f"🌐 {p['project_page']}")
        lines.append(f"    {' | '.join(links)}")
        lines.append("")

    return "\n".join(lines)


def format_markdown(papers, period, date_str):
    """格式化为 Markdown"""
    period_label = {"day": "Daily", "week": "Weekly", "month": "Monthly"}[period]
    lines = [
        f"# 🤗 Hugging Face {period_label} Papers — {date_str}",
        "",
        f"> 共 {len(papers)} 篇论文",
        "",
    ]
    for i, p in enumerate(papers, 1):
        authors_str = ", ".join(p["authors"][:5])
        if len(p["authors"]) > 5:
            authors_str += f" 等 {len(p['authors'])} 位作者"
        org_str = f" · **{p['organization']}**" if p["organization"] else ""

        lines.append(f"## {i}. {p['title']}")
        lines.append("")
        lines.append(f"- **Authors:** {authors_str}{org_str}")
        lines.append(f"- **Upvotes:** {p['upvotes']} | **Comments:** {p['comments']}")

        if p["ai_keywords"]:
            keywords = ", ".join(f"`{k}`" for k in p["ai_keywords"][:6])
            lines.append(f"- **Keywords:** {keywords}")

        if p["ai_summary"]:
            lines.append(f"- **AI Summary:** {p['ai_summary']}")

        links = [f"[Paper]({p['paper_url']})", f"[arXiv]({p['arxiv_url']})"]
        if p["github_repo"]:
            stars = f" ⭐{p['github_stars']}" if p["github_stars"] else ""
            links.append(f"[GitHub]({p['github_repo']}){stars}")
        if p["project_page"]:
            links.append(f"[Project]({p['project_page']})")
        lines.append(f"- **Links:** {' | '.join(links)}")

        if p["summary"]:
            # 截取前 300 字符
            summary = p["summary"][:300]
            if len(p["summary"]) > 300:
                summary += "..."
            lines.append(f"\n<details><summary>Abstract</summary>\n\n{p['summary']}\n</details>")

        lines.append("")

    return "\n".join(lines)


def format_json(papers, period, date_str):
    """格式化为 JSON"""
    output = {
        "period": period,
        "date": date_str,
        "count": len(papers),
        "papers": papers,
    }
    return json.dumps(output, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="🤗 Hugging Face Daily Papers 抓取工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  %(prog)s                          # 今日 daily papers
  %(prog)s --period week            # 本周热门
  %(prog)s --period month --all     # 本月全部
  %(prog)s --date 2026-03-01        # 指定日期
  %(prog)s --format json -o out.json
  %(prog)s --format md -o papers.md
""",
    )
    parser.add_argument(
        "--date", "-d",
        help="日期 (YYYY-MM-DD), 默认今天",
    )
    parser.add_argument(
        "--period", "-p",
        choices=["day", "week", "month"],
        default="day",
        help="时间范围: day (默认) / week / month",
    )
    parser.add_argument(
        "--limit", "-n",
        type=int,
        default=50,
        help="最多返回条数 (默认 50)",
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="拉取所有分页 (week/month 可能 >100 条)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["text", "json", "md"],
        default="text",
        help="输出格式: text (默认) / json / md",
    )
    parser.add_argument(
        "--output", "-o",
        help="输出到文件 (默认 stdout)",
    )
    parser.add_argument(
        "--sort",
        choices=["upvotes", "date", "comments"],
        help="排序方式 (默认按 API 返回顺序)",
    )

    args = parser.parse_args()

    # 确定日期显示
    if args.date:
        date_str = args.date
    else:
        tz = timezone(timedelta(hours=8))
        date_str = datetime.now(tz).strftime("%Y-%m-%d")

    # 抓取
    print(f"🔍 正在抓取 {args.period} papers (date={date_str})...", file=sys.stderr)

    if args.all:
        raw_papers = fetch_all_papers(date=args.date, period=args.period, limit=None)
    else:
        raw_papers = fetch_papers(date=args.date, period=args.period, limit=args.limit)

    # 解析
    papers = [parse_paper(p) for p in raw_papers]

    # 排序
    if args.sort:
        sort_key = {
            "upvotes": lambda p: -p["upvotes"],
            "date": lambda p: p["published_at"],
            "comments": lambda p: -p["comments"],
        }[args.sort]
        papers.sort(key=sort_key)

    # 限制数量
    if args.limit and not args.all:
        papers = papers[: args.limit]

    # 格式化
    formatters = {
        "text": format_text,
        "json": format_json,
        "md": format_markdown,
    }
    output = formatters[args.format](papers, args.period, date_str)

    # 输出
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"✅ 已保存到 {args.output} ({len(papers)} 篇)", file=sys.stderr)
    else:
        print(output)

    print(f"✅ 共 {len(papers)} 篇论文", file=sys.stderr)


if __name__ == "__main__":
    main()
