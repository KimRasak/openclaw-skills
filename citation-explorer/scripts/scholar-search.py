#!/usr/bin/env python3
"""
OpenAlex 学术论文搜索工具
Free API, no key required. Searches 250M+ academic works.

Usage:
  python3 scholar-search.py search "transformer architectures" --limit 10
  python3 scholar-search.py search "Qwen image" --sort citations --limit 5
  python3 scholar-search.py author "Yann LeCun" --limit 5
  python3 scholar-search.py doi "10.48550/arXiv.2308.12966"
  python3 scholar-search.py citations "10.48550/arXiv.2308.12966" --direction both
  python3 scholar-search.py deep "10.48550/arXiv.2308.12966"
  python3 scholar-search.py openalex "W4385346834"
"""
import argparse
import json
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

BASE_URL = "https://api.openalex.org"
CACHE_DIR = Path("/tmp/citation_explorer_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
REQUEST_INTERVAL = 0.1  # 100ms between requests

_last_request_time = 0.0


def _rate_limit():
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < REQUEST_INTERVAL:
        time.sleep(REQUEST_INTERVAL - elapsed)
    _last_request_time = time.time()


def _fetch_json(url: str, retries: int = 3) -> dict:
    """Fetch JSON from URL with retries and caching."""
    cache_key = urllib.parse.quote(url, safe="")[:200]
    cache_file = CACHE_DIR / f"{cache_key}.json"

    if cache_file.exists():
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < 24:
            return json.loads(cache_file.read_text())

    _rate_limit()
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "OpenClaw-CitationExplorer/1.0 (mailto:research@example.com)",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                cache_file.write_text(json.dumps(data, ensure_ascii=False))
                return data
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}: {e.reason}"
            if e.code == 429:
                time.sleep(attempt * 2)
                continue
            if e.code in (404, 403):
                break
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"

        if attempt < retries:
            time.sleep(attempt * 1.5)

    raise Exception(f"Failed to fetch {url}: {last_error}")


def _parse_work(work: dict) -> dict:
    """Extract structured metadata from an OpenAlex work object."""
    authorships = work.get("authorships", [])
    authors = []
    for a in authorships[:5]:
        author_obj = a.get("author", {})
        name = author_obj.get("display_name", "")
        if name:
            authors.append(name)

    source = work.get("primary_location", {}) or {}
    source_obj = source.get("source", {}) or {}
    venue = source_obj.get("display_name", "")

    oa_url = None
    best_oa = work.get("best_oa_location", {}) or {}
    if best_oa.get("pdf_url"):
        oa_url = best_oa["pdf_url"]
    elif best_oa.get("landing_page_url"):
        oa_url = best_oa["landing_page_url"]

    abstract_index = work.get("abstract_inverted_index")
    abstract = ""
    if abstract_index and isinstance(abstract_index, dict):
        positions = {}
        for word, idxs in abstract_index.items():
            for idx in idxs:
                positions[idx] = word
        if positions:
            abstract = " ".join(positions[k] for k in sorted(positions.keys()))

    return {
        "openalex_id": work.get("id", ""),
        "doi": (work.get("doi") or "").replace("https://doi.org/", ""),
        "title": work.get("title", ""),
        "year": work.get("publication_year"),
        "authors": authors,
        "abstract": abstract,
        "citations": work.get("cited_by_count", 0),
        "venue": venue,
        "oa_url": oa_url,
        "type": work.get("type", ""),
        "referenced_works": work.get("referenced_works", []),
        "cited_by_api_url": work.get("cited_by_api_url", ""),
    }


def search(query: str, limit: int = 10, sort: str = "relevance", year_from: int = None, json_output: bool = False):
    """Search papers by topic."""
    params = {
        "search": query,
        "per_page": min(limit, 50),
        "select": "id,doi,title,publication_year,authorships,cited_by_count,primary_location,best_oa_location,abstract_inverted_index,type,referenced_works,cited_by_api_url",
    }
    if sort == "citations":
        params["sort"] = "cited_by_count:desc"

    filters = []
    if year_from:
        filters.append(f"publication_year:>{year_from - 1}")
    if filters:
        params["filter"] = ",".join(filters)

    url = f"{BASE_URL}/works?{urllib.parse.urlencode(params)}"
    data = _fetch_json(url)
    results = [_parse_work(w) for w in data.get("results", [])]

    if json_output:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return results

    total = data.get("meta", {}).get("count", 0)
    print(f"\n📚 Found {total} results for \"{query}\" (showing top {len(results)})\n")

    for i, paper in enumerate(results, 1):
        authors_str = ", ".join(paper["authors"][:3])
        if len(paper["authors"]) > 3:
            authors_str += " et al."
        print(f"  {i}. [{paper['year']}] {paper['title']}")
        print(f"     Authors: {authors_str}")
        print(f"     Citations: {paper['citations']}  |  DOI: {paper['doi'] or 'N/A'}")
        if paper["venue"]:
            print(f"     Venue: {paper['venue']}")
        if paper["abstract"]:
            abs_preview = paper["abstract"][:200]
            if len(paper["abstract"]) > 200:
                abs_preview += "..."
            print(f"     Abstract: {abs_preview}")
        print()

    return results


def search_author(name: str, limit: int = 10, json_output: bool = False):
    """Search papers by author name."""
    params = {"search": name, "per_page": 5}
    url = f"{BASE_URL}/authors?{urllib.parse.urlencode(params)}"
    data = _fetch_json(url)

    authors = data.get("results", [])
    if not authors:
        print(f"No authors found for \"{name}\"")
        return []

    author = authors[0]
    author_id = author["id"]
    display_name = author.get("display_name", name)

    params = {
        "filter": f"authorships.author.id:{author_id}",
        "per_page": min(limit, 50),
        "sort": "cited_by_count:desc",
        "select": "id,doi,title,publication_year,authorships,cited_by_count,primary_location,best_oa_location,abstract_inverted_index,type,referenced_works,cited_by_api_url",
    }
    url = f"{BASE_URL}/works?{urllib.parse.urlencode(params)}"
    data = _fetch_json(url)
    results = [_parse_work(w) for w in data.get("results", [])]

    if json_output:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return results

    print(f"\n📚 Top papers by {display_name} (showing {len(results)})\n")
    for i, paper in enumerate(results, 1):
        print(f"  {i}. [{paper['year']}] {paper['title']}")
        print(f"     Citations: {paper['citations']}  |  DOI: {paper['doi'] or 'N/A'}")
        print()

    return results


def lookup_doi(doi: str, json_output: bool = False):
    """Look up a paper by DOI."""
    clean_doi = doi.replace("https://doi.org/", "")
    url = f"{BASE_URL}/works/doi:{clean_doi}"
    data = _fetch_json(url)
    paper = _parse_work(data)

    if json_output:
        print(json.dumps(paper, ensure_ascii=False, indent=2))
        return paper

    _print_paper_detail(paper)
    return paper


def lookup_openalex(openalex_id: str, json_output: bool = False):
    """Look up a paper by OpenAlex ID (e.g. W4385346834)."""
    if not openalex_id.startswith("https://"):
        openalex_id = f"https://openalex.org/{openalex_id}"
    url = f"{BASE_URL}/works/{openalex_id}"
    data = _fetch_json(url)
    paper = _parse_work(data)

    if json_output:
        print(json.dumps(paper, ensure_ascii=False, indent=2))
        return paper

    _print_paper_detail(paper)
    return paper


def get_citations(doi: str, direction: str = "both", limit: int = 20, json_output: bool = False):
    """Get citation chain: papers that cite this work and/or papers it references."""
    clean_doi = doi.replace("https://doi.org/", "")
    url = f"{BASE_URL}/works/doi:{clean_doi}"
    seed = _fetch_json(url)
    seed_parsed = _parse_work(seed)

    all_results = {"seed": seed_parsed, "references": [], "cited_by": []}

    if direction in ("references", "both"):
        ref_ids = seed.get("referenced_works", [])
        if ref_ids:
            id_filter = "|".join(ref_ids[:50])
            params = {
                "filter": f"openalex_id:{id_filter}",
                "per_page": min(limit, 50),
                "sort": "cited_by_count:desc",
                "select": "id,doi,title,publication_year,authorships,cited_by_count,primary_location,best_oa_location,abstract_inverted_index,type,referenced_works,cited_by_api_url",
            }
            refs_url = f"{BASE_URL}/works?{urllib.parse.urlencode(params)}"
            refs_data = _fetch_json(refs_url)
            all_results["references"] = [_parse_work(w) for w in refs_data.get("results", [])]

    if direction in ("cited_by", "both"):
        params = {
            "filter": f"cites:{seed['id']}",
            "per_page": min(limit, 50),
            "sort": "cited_by_count:desc",
            "select": "id,doi,title,publication_year,authorships,cited_by_count,primary_location,best_oa_location,abstract_inverted_index,type,referenced_works,cited_by_api_url",
        }
        citing_url = f"{BASE_URL}/works?{urllib.parse.urlencode(params)}"
        citing_data = _fetch_json(citing_url)
        all_results["cited_by"] = [_parse_work(w) for w in citing_data.get("results", [])]

    if json_output:
        print(json.dumps(all_results, ensure_ascii=False, indent=2))
        return all_results

    print(f"\n📚 Citation chain for: {seed_parsed['title']}\n")

    if all_results["references"]:
        print(f"  📖 References ({len(all_results['references'])} papers this work cites):")
        for i, p in enumerate(all_results["references"][:limit], 1):
            print(f"    {i}. [{p['year']}] {p['title']} (citations: {p['citations']})")
        print()

    if all_results["cited_by"]:
        print(f"  📝 Cited by ({len(all_results['cited_by'])} papers citing this work):")
        for i, p in enumerate(all_results["cited_by"][:limit], 1):
            print(f"    {i}. [{p['year']}] {p['title']} (citations: {p['citations']})")
        print()

    return all_results


def deep_read(doi: str, json_output: bool = False):
    """Fetch full metadata and abstract for a paper."""
    clean_doi = doi.replace("https://doi.org/", "")
    url = f"{BASE_URL}/works/doi:{clean_doi}"
    data = _fetch_json(url)
    paper = _parse_work(data)

    if json_output:
        print(json.dumps(paper, ensure_ascii=False, indent=2))
        return paper

    _print_paper_detail(paper)
    return paper


def _print_paper_detail(paper: dict):
    """Pretty-print detailed paper info."""
    print(f"\n{'='*70}")
    print(f"  Title:     {paper['title']}")
    print(f"  Year:      {paper['year']}")
    print(f"  Authors:   {', '.join(paper['authors'])}")
    print(f"  Citations: {paper['citations']}")
    print(f"  DOI:       {paper['doi'] or 'N/A'}")
    print(f"  Venue:     {paper['venue'] or 'N/A'}")
    print(f"  OA URL:    {paper['oa_url'] or 'N/A'}")
    print(f"  Type:      {paper['type']}")
    print(f"  OpenAlex:  {paper['openalex_id']}")
    if paper["abstract"]:
        print(f"\n  Abstract:")
        words = paper["abstract"].split()
        line = "    "
        for w in words:
            if len(line) + len(w) + 1 > 78:
                print(line)
                line = "    " + w
            else:
                line += " " + w if line.strip() else "    " + w
        if line.strip():
            print(line)
    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(description="OpenAlex Academic Paper Search")
    subparsers = parser.add_subparsers(dest="cmd", help="Command")

    # search
    sp = subparsers.add_parser("search", help="Search papers by topic")
    sp.add_argument("query", help="Search query")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--sort", choices=["relevance", "citations"], default="relevance")
    sp.add_argument("--year-from", type=int, default=None)
    sp.add_argument("--json", action="store_true")

    # author
    sp = subparsers.add_parser("author", help="Search papers by author")
    sp.add_argument("name", help="Author name")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--json", action="store_true")

    # doi
    sp = subparsers.add_parser("doi", help="Look up paper by DOI")
    sp.add_argument("doi", help="DOI string")
    sp.add_argument("--json", action="store_true")

    # openalex
    sp = subparsers.add_parser("openalex", help="Look up paper by OpenAlex ID")
    sp.add_argument("id", help="OpenAlex ID (e.g. W4385346834)")
    sp.add_argument("--json", action="store_true")

    # citations
    sp = subparsers.add_parser("citations", help="Get citation chain")
    sp.add_argument("doi", help="DOI of the paper")
    sp.add_argument("--direction", choices=["references", "cited_by", "both"], default="both")
    sp.add_argument("--limit", type=int, default=20)
    sp.add_argument("--json", action="store_true")

    # deep
    sp = subparsers.add_parser("deep", help="Deep read: full metadata + abstract")
    sp.add_argument("doi", help="DOI of the paper")
    sp.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    if args.cmd == "search":
        search(args.query, args.limit, args.sort, args.year_from, args.json)
    elif args.cmd == "author":
        search_author(args.name, args.limit, args.json)
    elif args.cmd == "doi":
        lookup_doi(args.doi, args.json)
    elif args.cmd == "openalex":
        lookup_openalex(args.id, args.json)
    elif args.cmd == "citations":
        get_citations(args.doi, args.direction, args.limit, args.json)
    elif args.cmd == "deep":
        deep_read(args.doi, args.json)


if __name__ == "__main__":
    main()
