#!/usr/bin/env python3
"""
AlphaXiv Trending Papers 抓取脚本

用法:
  # 抓取热门论文 (默认 Hot, All time, 20 篇)
  python3 alphaxiv_papers.py

  # 指定排序方式
  python3 alphaxiv_papers.py --sort Hot          # 热门 (默认)
  python3 alphaxiv_papers.py --sort Comments      # 评论数
  python3 alphaxiv_papers.py --sort Views         # 浏览量
  python3 alphaxiv_papers.py --sort Likes         # 点赞数
  python3 alphaxiv_papers.py --sort GitHub        # GitHub stars
  python3 alphaxiv_papers.py --sort "Twitter (X)" # Twitter/X 热度

  # 指定时间范围
  python3 alphaxiv_papers.py --interval "3 Days"
  python3 alphaxiv_papers.py --interval "7 Days"
  python3 alphaxiv_papers.py --interval "30 Days"
  python3 alphaxiv_papers.py --interval "90 Days"
  python3 alphaxiv_papers.py --interval "All time"  # 默认

  # 按 topic 过滤 (arXiv 分类)
  python3 alphaxiv_papers.py --topics cs.AI cs.CL

  # 分页加载更多 (Load more)
  python3 alphaxiv_papers.py --pages 3            # 加载前 3 页 (60 篇)

  # 限制数量
  python3 alphaxiv_papers.py --limit 10

  # 输出格式
  python3 alphaxiv_papers.py --format json
  python3 alphaxiv_papers.py --format md --output papers.md

API (逆向分析):
  Base: https://api.alphaxiv.org
  GET /papers/v3/feed
  参数:
    pageNum       - 页码, 从 0 开始
    pageSize      - 每页数量, 默认 20
    sort          - Hot | Comments | Views | Likes | GitHub | Twitter (X) | Recommended
    interval      - 3 Days | 7 Days | 30 Days | 90 Days | All time
    topics        - JSON 数组, 如 ["cs.AI","cs.CL"]
    organizations - JSON 数组, 如 ["Google"]
    source        - 来源过滤 (可选)
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
import urllib.parse

API_BASE = "https://api.alphaxiv.org"
PAPER_BASE = "https://www.alphaxiv.org"
ARXIV_BASE = "https://arxiv.org/abs"
PAGE_SIZE = 20

VALID_SORTS = ["Hot", "Comments", "Views", "Likes", "GitHub", "Twitter (X)", "Recommended"]
VALID_INTERVALS = ["3 Days", "7 Days", "30 Days", "90 Days", "All time"]


def fetch_page(page_num=0, sort="Hot", interval="All time", topics=None,
               organizations=None, page_size=PAGE_SIZE):
    """从 AlphaXiv API 抓取一页论文"""
    params = {
        "pageNum": str(page_num),
        "sort": sort,
        "pageSize": str(page_size),
        "interval": interval,
        "topics": json.dumps(topics or []),
    }
    if organizations:
        params["organizations"] = json.dumps(organizations)

    url = f"{API_BASE}/papers/v3/feed?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "alphaxiv-papers-fetcher/1.0",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            return data.get("papers", []), data.get("page", page_num)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            err = json.loads(body)
            msg = err.get("error", {})
            if isinstance(msg, dict):
                msg = msg.get("message", body)
            print(f"API Error: {msg}", file=sys.stderr)
        except json.JSONDecodeError:
            print(f"HTTP Error {e.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Connection Error: {e.reason}", file=sys.stderr)
        sys.exit(1)


def fetch_papers(sort="Hot", interval="All time", topics=None,
                 organizations=None, pages=1, limit=None):
    """分页拉取论文, 支持 Load more"""
    all_papers = []
    for page in range(pages):
        papers, _ = fetch_page(
            page_num=page, sort=sort, interval=interval,
            topics=topics, organizations=organizations,
        )
        if not papers:
            break
        all_papers.extend(papers)
        if limit and len(all_papers) >= limit:
            break
        if len(papers) < PAGE_SIZE:
            # 已到最后一页
            break

    if limit:
        all_papers = all_papers[:limit]
    return all_papers


def parse_paper(raw):
    """解析单篇论文数据"""
    metrics = raw.get("metrics", {})
    visits = metrics.get("visits_count", {})
    summary_obj = raw.get("paper_summary") or {}

    return {
        "id": raw.get("universal_paper_id", ""),
        "group_id": raw.get("paper_group_id", ""),
        "title": raw.get("title", ""),
        "abstract": raw.get("abstract", ""),
        "summary": summary_obj.get("summary", "") if isinstance(summary_obj, dict) else "",
        "key_insights": summary_obj.get("keyInsights", []) if isinstance(summary_obj, dict) else [],
        "authors": raw.get("authors", []),
        "topics": raw.get("topics", []),
        "organizations": [o.get("name", "") for o in raw.get("organization_info", [])],
        "votes": metrics.get("total_votes", 0),
        "public_votes": metrics.get("public_total_votes", 0),
        "views_all": visits.get("all", 0),
        "views_7d": visits.get("last_7_days", 0),
        "x_likes": metrics.get("x_likes", 0),
        "github_stars": raw.get("github_stars", 0),
        "github_url": raw.get("github_url", ""),
        "published_at": raw.get("first_publication_date", ""),
        "updated_at": raw.get("updated_at", ""),
        "alphaxiv_url": f"{PAPER_BASE}/abs/{raw.get('universal_paper_id', '')}",
        "arxiv_url": f"{ARXIV_BASE}/{raw.get('universal_paper_id', '')}",
        "image_url": raw.get("image_url", ""),
    }


def format_text(papers, sort, interval, topics):
    """格式化为终端文本输出"""
    filter_parts = [f"Sort: {sort}", f"Interval: {interval}"]
    if topics:
        filter_parts.append(f"Topics: {', '.join(topics)}")

    lines = [
        f"🔬 AlphaXiv Trending Papers",
        f"   {' | '.join(filter_parts)}",
        f"   共 {len(papers)} 篇",
        "=" * 70,
        "",
    ]
    for i, p in enumerate(papers, 1):
        authors_str = ", ".join(p["authors"][:3])
        if len(p["authors"]) > 3:
            authors_str += f" 等 {len(p['authors'])} 位作者"
        org_str = f" · 🏢 {', '.join(p['organizations'])}" if p["organizations"] else ""

        lines.append(f"[{i}] {p['title']}")
        lines.append(
            f"    👁️ {p['views_all']}  ⬆️ {p['public_votes']}  "
            f"{'⭐ ' + str(p['github_stars']) + '  ' if p['github_stars'] else ''}"
            f"👤 {authors_str}{org_str}"
        )

        if p["summary"]:
            lines.append(f"    📝 {p['summary']}")

        if p["topics"]:
            lines.append(f"    🏷️ {', '.join(p['topics'][:6])}")

        links = [f"📄 {p['alphaxiv_url']}"]
        if p["github_url"]:
            lines.append(f"    💻 {p['github_url']}")
        lines.append(f"    {links[0]}")
        lines.append("")

    return "\n".join(lines)


def format_markdown(papers, sort, interval, topics):
    """格式化为 Markdown"""
    filter_parts = [f"**Sort:** {sort}", f"**Interval:** {interval}"]
    if topics:
        filter_parts.append(f"**Topics:** {', '.join(topics)}")

    lines = [
        f"# 🔬 AlphaXiv Trending Papers",
        "",
        f"> {' | '.join(filter_parts)}",
        f"> 共 {len(papers)} 篇论文",
        "",
    ]
    for i, p in enumerate(papers, 1):
        authors_str = ", ".join(p["authors"][:5])
        if len(p["authors"]) > 5:
            authors_str += f" 等 {len(p['authors'])} 位作者"
        org_str = f" · **{', '.join(p['organizations'])}**" if p["organizations"] else ""

        lines.append(f"## {i}. {p['title']}")
        lines.append("")
        lines.append(f"- **Authors:** {authors_str}{org_str}")
        lines.append(f"- **Views:** {p['views_all']} (7d: {p['views_7d']}) | **Votes:** {p['public_votes']}")

        if p["github_stars"]:
            lines.append(f"- **GitHub:** [{p['github_url']}]({p['github_url']}) ⭐ {p['github_stars']}")

        if p["topics"]:
            topic_tags = ", ".join(f"`{t}`" for t in p["topics"][:8])
            lines.append(f"- **Topics:** {topic_tags}")

        if p["summary"]:
            lines.append(f"- **Summary:** {p['summary']}")

        if p["key_insights"]:
            lines.append("- **Key Insights:**")
            for insight in p["key_insights"][:3]:
                lines.append(f"  - {insight}")

        links = [f"[AlphaXiv]({p['alphaxiv_url']})", f"[arXiv]({p['arxiv_url']})"]
        if p["github_url"]:
            links.append(f"[GitHub]({p['github_url']})")
        lines.append(f"- **Links:** {' | '.join(links)}")

        if p["abstract"]:
            lines.append(f"\n<details><summary>Abstract</summary>\n\n{p['abstract']}\n</details>")

        lines.append("")

    return "\n".join(lines)


def format_json(papers, sort, interval, topics):
    """格式化为 JSON"""
    output = {
        "source": "alphaxiv",
        "sort": sort,
        "interval": interval,
        "topics": topics or [],
        "count": len(papers),
        "papers": papers,
    }
    return json.dumps(output, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="🔬 AlphaXiv Trending Papers 抓取工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
排序选项: Hot, Comments, Views, Likes, GitHub, Twitter (X)
时间范围: 3 Days, 7 Days, 30 Days, 90 Days, All time

示例:
  %(prog)s                                  # 热门论文 (默认)
  %(prog)s --sort Views --interval "7 Days" # 过去 7 天浏览量最高
  %(prog)s --topics cs.AI cs.CL             # 按主题过滤
  %(prog)s --pages 3                        # 加载 3 页 (60 篇)
  %(prog)s --sort GitHub                    # GitHub stars 最高
  %(prog)s --format json -o trending.json   # JSON 输出
  %(prog)s --format md -o papers.md         # Markdown 输出
""",
    )
    parser.add_argument(
        "--sort", "-s",
        choices=VALID_SORTS,
        default="Hot",
        help="排序方式 (默认: Hot)",
    )
    parser.add_argument(
        "--interval", "-i",
        choices=VALID_INTERVALS,
        default="All time",
        help="时间范围 (默认: All time)",
    )
    parser.add_argument(
        "--topics", "-t",
        nargs="+",
        help="按 topic 过滤 (arXiv 分类, 如 cs.AI cs.CL)",
    )
    parser.add_argument(
        "--pages", "-p",
        type=int,
        default=1,
        help="加载页数 (每页 20 篇, 默认 1)",
    )
    parser.add_argument(
        "--limit", "-n",
        type=int,
        help="最多返回条数",
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

    args = parser.parse_args()

    # 抓取
    desc = f"sort={args.sort}, interval={args.interval}"
    if args.topics:
        desc += f", topics={args.topics}"
    print(f"🔍 正在抓取 AlphaXiv papers ({desc})...", file=sys.stderr)

    raw_papers = fetch_papers(
        sort=args.sort,
        interval=args.interval,
        topics=args.topics,
        pages=args.pages,
        limit=args.limit,
    )

    # 解析
    papers = [parse_paper(p) for p in raw_papers]

    # 格式化
    formatters = {
        "text": format_text,
        "json": format_json,
        "md": format_markdown,
    }
    output = formatters[args.format](papers, args.sort, args.interval, args.topics)

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
