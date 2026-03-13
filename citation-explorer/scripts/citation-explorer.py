#!/usr/bin/env python3
"""
Citation Explorer — 以论文为中心的发散式引用链探索引擎

从种子论文出发，沿引用关系（references + cited_by）向外层层扩展，
使用优先队列发现新的研究方向和重要文献。

Usage:
  # 以 DOI 为种子，优先策略扩展 2 层，最多 30 篇
  python3 citation-explorer.py explore \
    --seed "10.48550/arXiv.2308.12966" \
    --depth 2 --max-papers 30 --strategy priority \
    --output exploration.md

  # 以标题关键词定位种子
  python3 citation-explorer.py explore \
    --seed-query "Qwen-VL A Versatile Vision-Language Model" \
    --depth 2 --max-papers 20 \
    --output exploration.md

  # 排除已探索论文，进行第二轮探索
  python3 citation-explorer.py explore \
    --seed "10.1234/new-paper" \
    --depth 2 --max-papers 20 \
    --exclude-visited exploration.md \
    --output exploration_round2.md
"""
import argparse
import heapq
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from importlib import import_module

# Import functions from scholar-search.py
_ss_path = Path(__file__).parent / "scholar-search.py"
import importlib.util

_spec = importlib.util.spec_from_file_location("scholar_search", _ss_path)
_ss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ss)

search_papers = _ss.search
fetch_json = _ss._fetch_json
parse_work = _ss._parse_work
BASE_URL = _ss.BASE_URL

import urllib.parse


class CitationExplorer:
    def __init__(
        self,
        max_papers: int = 30,
        max_depth: int = 2,
        strategy: str = "priority",
        min_citations: int = 0,
        year_from: int = None,
        focus_terms: list = None,
        exclude_terms: list = None,
    ):
        self.max_papers = max_papers
        self.max_depth = max_depth
        self.strategy = strategy
        self.min_citations = min_citations
        self.year_from = year_from
        self.focus_terms = [t.lower() for t in (focus_terms or [])]
        self.exclude_terms = [t.lower() for t in (exclude_terms or [])]
        self._skipped_count = 0

        self.visited = {}  # openalex_id -> paper dict
        self.edges = []  # (source_id, target_id, relation)
        self.layers = defaultdict(list)  # layer_num -> [openalex_id, ...]
        self._counter = 0  # for heap tie-breaking

    def _score_paper(self, paper: dict, layer: int) -> float:
        """Compute exploration priority score. Higher = explore first."""
        current_year = time.localtime().tm_year
        year = paper.get("year") or 2000
        recency = max(0, min(1.0, (year - 2015) / (current_year - 2015))) if current_year > 2015 else 0.5

        citations = paper.get("citations", 0)
        citation_impact = min(1.0, citations / 500) if citations > 0 else 0.0

        novelty = 1.0 if paper["openalex_id"] not in self.visited else 0.0

        depth_penalty = 1.0 / (1 + layer * 0.3)

        score = (recency * 0.4 + citation_impact * 0.4 + novelty * 0.2) * depth_penalty

        # Boost papers matching focus terms
        if self.focus_terms:
            text = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()
            if any(t in text for t in self.focus_terms):
                score *= 1.5

        return score

    def _should_include(self, paper: dict) -> bool:
        """Filter by citations, year, and topic focus/exclusion."""
        if paper.get("citations", 0) < self.min_citations:
            return False
        if self.year_from and (paper.get("year") or 0) < self.year_from:
            return False
        if not paper.get("title"):
            return False

        text = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()

        # Exclude papers matching excluded topics
        if self.exclude_terms:
            for term in self.exclude_terms:
                if term in text:
                    self._skipped_count += 1
                    return False

        # If focus terms are set, paper must match at least one
        if self.focus_terms:
            if not any(t in text for t in self.focus_terms):
                self._skipped_count += 1
                return False

        return True

    def _fetch_work_by_id(self, openalex_id: str) -> dict:
        """Fetch a single work by OpenAlex ID."""
        url = f"{BASE_URL}/works/{openalex_id}"
        try:
            data = fetch_json(url)
            return parse_work(data)
        except Exception:
            return None

    def _fetch_references(self, paper: dict, limit: int = 25) -> list:
        """Fetch papers that this work references."""
        ref_ids = paper.get("referenced_works", [])
        if not ref_ids:
            return []

        id_filter = "|".join(ref_ids[:limit])
        params = {
            "filter": f"openalex_id:{id_filter}",
            "per_page": min(limit, 50),
            "sort": "cited_by_count:desc",
            "select": "id,doi,title,publication_year,authorships,cited_by_count,primary_location,best_oa_location,abstract_inverted_index,type,referenced_works,cited_by_api_url",
        }
        url = f"{BASE_URL}/works?{urllib.parse.urlencode(params)}"
        try:
            data = fetch_json(url)
            return [parse_work(w) for w in data.get("results", [])]
        except Exception:
            return []

    def _fetch_cited_by(self, paper: dict, limit: int = 25) -> list:
        """Fetch papers that cite this work."""
        openalex_id = paper["openalex_id"]
        params = {
            "filter": f"cites:{openalex_id}",
            "per_page": min(limit, 50),
            "sort": "cited_by_count:desc",
            "select": "id,doi,title,publication_year,authorships,cited_by_count,primary_location,best_oa_location,abstract_inverted_index,type,referenced_works,cited_by_api_url",
        }
        url = f"{BASE_URL}/works?{urllib.parse.urlencode(params)}"
        try:
            data = fetch_json(url)
            return [parse_work(w) for w in data.get("results", [])]
        except Exception:
            return []

    def _resolve_seed(self, seed: str = None, seed_query: str = None) -> dict:
        """Resolve seed paper from DOI, OpenAlex ID, or search query."""
        if seed:
            seed = seed.strip()
            if seed.startswith("W") and seed[1:].isdigit():
                paper = self._fetch_work_by_id(f"https://openalex.org/{seed}")
                if paper:
                    return paper
            clean = seed.replace("https://doi.org/", "")
            url = f"{BASE_URL}/works/doi:{clean}"
            try:
                data = fetch_json(url)
                return parse_work(data)
            except Exception:
                pass
            # try as OpenAlex URL
            if "openalex.org" in seed:
                try:
                    data = fetch_json(f"{BASE_URL}/works/{seed}")
                    return parse_work(data)
                except Exception:
                    pass

        if seed_query:
            results = search_papers(seed_query, limit=1, json_output=False)
            if results:
                return results[0]

        raise ValueError("Could not resolve seed paper. Provide a valid DOI, OpenAlex ID, or --seed-query.")

    def explore(self, seed: str = None, seed_query: str = None, exclude_ids: set = None) -> dict:
        """Run the citation exploration from a seed paper."""
        if exclude_ids:
            for eid in exclude_ids:
                self.visited[eid] = {"openalex_id": eid, "title": "[excluded]", "year": 0, "citations": 0}

        seed_paper = self._resolve_seed(seed, seed_query)
        seed_id = seed_paper["openalex_id"]
        self.visited[seed_id] = seed_paper
        self.layers[0].append(seed_id)

        print(f"\n🌱 Seed: {seed_paper['title']} ({seed_paper['year']})")
        print(f"   Citations: {seed_paper['citations']}  |  DOI: {seed_paper.get('doi', 'N/A')}")
        if self.focus_terms:
            print(f"   🔍 Focus: {', '.join(self.focus_terms)}")
        if self.exclude_terms:
            print(f"   🚫 Exclude: {', '.join(self.exclude_terms)}")

        if self.strategy == "priority":
            self._explore_priority(seed_paper)
        elif self.strategy == "breadth":
            self._explore_bfs(seed_paper)
        elif self.strategy == "depth":
            self._explore_dfs(seed_paper, 0)

        actual_papers = {k: v for k, v in self.visited.items() if v.get("title") != "[excluded]"}
        skip_msg = f", {self._skipped_count} filtered out" if self._skipped_count else ""
        print(f"\n✅ Exploration complete: {len(actual_papers)} papers, {len(self.edges)} edges, {len(self.layers)} layers{skip_msg}")

        return {
            "seed": seed_paper,
            "papers": actual_papers,
            "edges": self.edges,
            "layers": dict(self.layers),
        }

    def _explore_priority(self, seed_paper: dict):
        """Priority-queue driven exploration."""
        # heap items: (-score, counter, openalex_id, layer)
        heap = []

        def _enqueue_neighbors(paper: dict, current_layer: int):
            if current_layer >= self.max_depth:
                return
            next_layer = current_layer + 1

            refs = self._fetch_references(paper, limit=15)
            for ref in refs:
                if ref["openalex_id"] not in self.visited and self._should_include(ref):
                    score = self._score_paper(ref, next_layer)
                    self._counter += 1
                    heapq.heappush(heap, (-score, self._counter, ref, next_layer, paper["openalex_id"], "references"))

            cited = self._fetch_cited_by(paper, limit=15)
            for c in cited:
                if c["openalex_id"] not in self.visited and self._should_include(c):
                    score = self._score_paper(c, next_layer)
                    self._counter += 1
                    heapq.heappush(heap, (-score, self._counter, c, next_layer, paper["openalex_id"], "cited_by"))

        _enqueue_neighbors(seed_paper, 0)

        while heap and len([v for v in self.visited.values() if v.get("title") != "[excluded]"]) < self.max_papers:
            neg_score, _, paper, layer, source_id, relation = heapq.heappop(heap)

            if paper["openalex_id"] in self.visited:
                continue

            self.visited[paper["openalex_id"]] = paper
            self.layers[layer].append(paper["openalex_id"])
            self.edges.append((source_id, paper["openalex_id"], relation))

            score = -neg_score
            print(f"   [{layer}] score={score:.2f} | [{paper['year']}] {paper['title'][:60]}... (cit: {paper['citations']})")

            _enqueue_neighbors(paper, layer)

    def _explore_bfs(self, seed_paper: dict):
        """Standard BFS exploration."""
        queue = [(seed_paper, 0)]

        while queue and len([v for v in self.visited.values() if v.get("title") != "[excluded]"]) < self.max_papers:
            current, layer = queue.pop(0)

            if layer >= self.max_depth:
                continue

            next_layer = layer + 1

            refs = self._fetch_references(current, limit=10)
            cited = self._fetch_cited_by(current, limit=10)

            for ref in refs:
                if ref["openalex_id"] not in self.visited and self._should_include(ref):
                    self.visited[ref["openalex_id"]] = ref
                    self.layers[next_layer].append(ref["openalex_id"])
                    self.edges.append((current["openalex_id"], ref["openalex_id"], "references"))
                    queue.append((ref, next_layer))
                    print(f"   [{next_layer}] [{ref['year']}] {ref['title'][:60]}... (cit: {ref['citations']})")
                    if len([v for v in self.visited.values() if v.get("title") != "[excluded]"]) >= self.max_papers:
                        break

            if len([v for v in self.visited.values() if v.get("title") != "[excluded]"]) >= self.max_papers:
                break

            for c in cited:
                if c["openalex_id"] not in self.visited and self._should_include(c):
                    self.visited[c["openalex_id"]] = c
                    self.layers[next_layer].append(c["openalex_id"])
                    self.edges.append((current["openalex_id"], c["openalex_id"], "cited_by"))
                    queue.append((c, next_layer))
                    print(f"   [{next_layer}] [{c['year']}] {c['title'][:60]}... (cit: {c['citations']})")
                    if len([v for v in self.visited.values() if v.get("title") != "[excluded]"]) >= self.max_papers:
                        break

    def _explore_dfs(self, paper: dict, layer: int):
        """DFS-style exploration following highest-score path."""
        if layer >= self.max_depth:
            return
        if len([v for v in self.visited.values() if v.get("title") != "[excluded]"]) >= self.max_papers:
            return

        refs = self._fetch_references(paper, limit=10)
        cited = self._fetch_cited_by(paper, limit=10)

        candidates = []
        for ref in refs:
            if ref["openalex_id"] not in self.visited and self._should_include(ref):
                candidates.append((ref, "references"))
        for c in cited:
            if c["openalex_id"] not in self.visited and self._should_include(c):
                candidates.append((c, "cited_by"))

        candidates.sort(key=lambda x: self._score_paper(x[0], layer + 1), reverse=True)

        for cand, relation in candidates:
            if len([v for v in self.visited.values() if v.get("title") != "[excluded]"]) >= self.max_papers:
                break
            if cand["openalex_id"] in self.visited:
                continue

            self.visited[cand["openalex_id"]] = cand
            self.layers[layer + 1].append(cand["openalex_id"])
            self.edges.append((paper["openalex_id"], cand["openalex_id"], relation))

            score = self._score_paper(cand, layer + 1)
            print(f"   [{layer+1}] score={score:.2f} | [{cand['year']}] {cand['title'][:60]}... (cit: {cand['citations']})")

            self._explore_dfs(cand, layer + 1)


def _extract_visited_ids(filepath: str) -> set:
    """Extract OpenAlex IDs from a previous exploration report."""
    ids = set()
    try:
        content = Path(filepath).read_text()
        for match in re.finditer(r"https://openalex\.org/(W\d+)", content):
            ids.add(f"https://openalex.org/{match.group(1)}")
    except Exception:
        pass
    return ids


THEME_PATTERNS = {
    "Image Generation": ["image generation", "text-to-image", "diffusion", "generative"],
    "Image Editing": ["image edit", "inpainting", "instruct.*edit", "manipulation"],
    "Multimodal Understanding": ["multimodal", "vision-language", "visual question", "vqa"],
    "Object Detection": ["object detect", "yolo", "detection", "bounding box"],
    "Image Segmentation": ["segment", "panoptic", "instance segment", "semantic segment"],
    "Video Understanding": ["video", "temporal", "action recognition"],
    "3D Vision": ["3d", "nerf", "point cloud", "depth estimation"],
    "OCR & Document": ["ocr", "document", "text recognition", "layout"],
    "Image Restoration": ["super-resolution", "denoising", "restoration", "enhancement"],
    "Layer Decomposition": ["layer", "decompos", "transparent", "alpha matte"],
    "Training & Optimization": ["training", "fine-tun", "pre-train", "optimization", "lora"],
    "Evaluation & Benchmark": ["benchmark", "evaluation", "metric", "dataset"],
    "Large Language Models": ["llm", "language model", "gpt", "transformer"],
    "Reinforcement Learning": ["reinforcement", "reward", "rlhf", "ppo"],
    "Medical & Healthcare": ["medical", "health", "clinical", "radiology", "pathology"],
    "Remote Sensing": ["remote sens", "satellite", "aerial", "geospatial"],
    "Robotics & Embodied": ["robot", "embodied", "manipulation", "navigation"],
    "Speech & Audio": ["speech", "audio", "voice", "acoustic"],
    "Retrieval & RAG": ["retrieval", "rag", "search", "information retriev"],
    "Code & Programming": ["code generat", "program synth", "software engineer"],
    "Autonomous Driving": ["autonomous driv", "self-driv", "vehicle", "lidar"],
    "Knowledge Graph": ["knowledge graph", "ontology", "entity relation"],
    "Recommendation": ["recommend", "collaborative filter", "user prefer"],
    "NLP & Text": ["text classif", "sentiment", "named entity", "relation extract", "summariz"],
    "Graph Neural Network": ["graph neural", "gnn", "node classif", "graph convol"],
}


def _classify_paper(paper: dict) -> set:
    """Classify a single paper into themes based on title+abstract."""
    if paper.get("title") == "[excluded]":
        return set()
    text = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()
    matched = set()
    for theme, patterns in THEME_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, text):
                matched.add(theme)
                break
    return matched


def _identify_themes(papers: dict, edges: list) -> list:
    """Identify research themes and classify each paper into them."""
    keyword_groups = defaultdict(list)

    for pid, paper in papers.items():
        for theme in _classify_paper(paper):
            keyword_groups[theme].append(pid)

    themes = []
    for theme, pids in sorted(keyword_groups.items(), key=lambda x: -len(x[1])):
        if len(pids) >= 1:
            themes.append({"name": theme, "paper_ids": pids, "count": len(pids)})

    return themes


def generate_theme_graph(result: dict, themes: list) -> dict:
    """Generate a topic-level graph: nodes = research themes, edges = citation flow between topics.

    Edge weight = number of citation relationships between papers of different themes.
    Node weight = total papers in that theme.
    """
    papers = result["papers"]
    edges = result["edges"]
    layers = result["layers"]

    # Build paper -> set of themes mapping
    paper_themes = {}
    for pid, paper in papers.items():
        paper_themes[pid] = _classify_paper(paper)

    # Identify the seed paper's themes to mark as "seed topics"
    seed = result["seed"]
    seed_id = seed["openalex_id"]
    seed_themes = paper_themes.get(seed_id, set())

    # Compute min layer for each theme (how early it was discovered)
    layer_lookup = {}
    for layer_num, ids in layers.items():
        for pid in ids:
            layer_lookup[pid] = layer_num

    theme_min_layer = {}
    for theme_info in themes:
        min_l = min(layer_lookup.get(pid, 99) for pid in theme_info["paper_ids"])
        theme_min_layer[theme_info["name"]] = min_l

    # Compute total citations per theme
    theme_citations = {}
    for theme_info in themes:
        total_cit = sum(
            papers.get(pid, {}).get("citations", 0) for pid in theme_info["paper_ids"]
        )
        theme_citations[theme_info["name"]] = total_cit

    # Compute representative years (median year of papers in the theme)
    theme_years = {}
    for theme_info in themes:
        years = sorted(
            papers.get(pid, {}).get("year", 2020) for pid in theme_info["paper_ids"]
            if papers.get(pid, {}).get("year")
        )
        theme_years[theme_info["name"]] = years[len(years) // 2] if years else 2020

    # Build theme nodes
    theme_nodes = []
    for theme_info in themes:
        name = theme_info["name"]
        theme_nodes.append({
            "id": name,
            "name": name,
            "paper_count": theme_info["count"],
            "total_citations": theme_citations.get(name, 0),
            "median_year": theme_years.get(name, 2020),
            "layer": theme_min_layer.get(name, 0),
            "is_seed_topic": name in seed_themes,
            "paper_titles": [
                papers.get(pid, {}).get("title", "")
                for pid in theme_info["paper_ids"][:5]
            ],
        })

    # Build inter-theme edges from paper citation relationships
    theme_edge_weights = defaultdict(int)
    theme_names_set = {t["name"] for t in themes}

    for src_pid, tgt_pid, rel in edges:
        src_th = paper_themes.get(src_pid, set())
        tgt_th = paper_themes.get(tgt_pid, set())
        for st in src_th:
            for tt in tgt_th:
                if st != tt and st in theme_names_set and tt in theme_names_set:
                    key = (st, tt) if st < tt else (tt, st)
                    theme_edge_weights[key] += 1

    theme_edges = []
    for (src, tgt), weight in sorted(theme_edge_weights.items(), key=lambda x: -x[1]):
        theme_edges.append({
            "source": src,
            "target": tgt,
            "weight": weight,
        })

    return {
        "type": "theme_graph",
        "seed_title": seed.get("title", ""),
        "seed_year": seed.get("year"),
        "nodes": theme_nodes,
        "edges": theme_edges,
    }


def generate_report(result: dict, themes: list) -> str:
    """Generate a Markdown exploration report."""
    seed = result["seed"]
    papers = result["papers"]
    edges = result["edges"]
    layers = result["layers"]

    lines = []
    lines.append(f"# Citation Exploration Report")
    lines.append(f"")
    lines.append(f"**Seed**: {seed['title']} ({seed['year']})")
    lines.append(f"**DOI**: {seed.get('doi', 'N/A')}")
    lines.append(f"**OpenAlex**: {seed['openalex_id']}")
    lines.append(f"**Total papers**: {len([p for p in papers.values() if p.get('title') != '[excluded]'])}")
    lines.append(f"**Edges**: {len(edges)}")
    lines.append(f"**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"")

    # Build edge lookup for relation info
    edge_map = {}
    for src, tgt, rel in edges:
        edge_map[tgt] = (src, rel)

    paper_idx = {}
    idx = 1

    for layer_num in sorted(layers.keys()):
        layer_ids = layers[layer_num]
        if layer_num == 0:
            lines.append(f"## Layer 0 — Seed")
        elif layer_num == 1:
            lines.append(f"## Layer 1 — Direct References & Citing Works")
        else:
            lines.append(f"## Layer {layer_num} — Extended Network")

        lines.append(f"")
        lines.append(f"| # | Title | Year | Citations | Relation | DOI |")
        lines.append(f"|---|-------|------|-----------|----------|-----|")

        for pid in layer_ids:
            p = papers.get(pid, {})
            if p.get("title") == "[excluded]":
                continue
            paper_idx[pid] = idx
            rel = "seed"
            if pid in edge_map:
                _, r = edge_map[pid]
                rel = r
            doi_str = p.get("doi", "N/A") or "N/A"
            lines.append(f"| {idx} | {p.get('title', 'N/A')} | {p.get('year', 'N/A')} | {p.get('citations', 0)} | {rel} | {doi_str} |")
            idx += 1

        lines.append(f"")

        # Show abstracts for this layer
        has_abstract = False
        for pid in layer_ids:
            p = papers.get(pid, {})
            if p.get("title") == "[excluded]":
                continue
            if p.get("abstract"):
                if not has_abstract:
                    lines.append(f"<details>")
                    lines.append(f"<summary>Abstracts (Layer {layer_num})</summary>")
                    lines.append(f"")
                    has_abstract = True
                n = paper_idx.get(pid, "?")
                abs_text = p["abstract"][:300]
                if len(p["abstract"]) > 300:
                    abs_text += "..."
                lines.append(f"**[{n}] {p['title']}**")
                lines.append(f"> {abs_text}")
                lines.append(f"")

        if has_abstract:
            lines.append(f"</details>")
            lines.append(f"")

    if themes:
        lines.append(f"## Discovered Themes")
        lines.append(f"")
        for i, theme in enumerate(themes, 1):
            paper_refs = ", ".join(
                f"paper {paper_idx.get(pid, '?')}" for pid in theme["paper_ids"][:5]
                if papers.get(pid, {}).get("title") != "[excluded]"
            )
            lines.append(f"{i}. **{theme['name']}** ({theme['count']} papers) — {paper_refs}")
        lines.append(f"")

    # Suggest next seeds
    candidates = []
    for pid, p in papers.items():
        if p.get("title") == "[excluded]" or pid == seed["openalex_id"]:
            continue
        score = (p.get("year", 2000) - 2015) * 0.3 + min(p.get("citations", 0) / 100, 5)
        candidates.append((score, pid, p))
    candidates.sort(reverse=True)

    if candidates:
        lines.append(f"## Suggested Next Seeds")
        lines.append(f"")
        for _, pid, p in candidates[:5]:
            n = paper_idx.get(pid, "?")
            lines.append(f"- **{p['title']}** (paper {n}, {p['year']}, {p['citations']} cit.) — DOI: {p.get('doi', 'N/A')}")
        lines.append(f"")

    return "\n".join(lines)


def generate_graph_json(result: dict) -> dict:
    """Generate a JSON citation graph."""
    papers = result["papers"]
    edges = result["edges"]
    layers = result["layers"]

    layer_lookup = {}
    for layer_num, ids in layers.items():
        for pid in ids:
            layer_lookup[pid] = layer_num

    nodes = []
    for pid, p in papers.items():
        if p.get("title") == "[excluded]":
            continue
        nodes.append({
            "id": pid,
            "title": p.get("title", ""),
            "year": p.get("year"),
            "citations": p.get("citations", 0),
            "doi": p.get("doi", ""),
            "layer": layer_lookup.get(pid, -1),
        })

    edge_list = []
    for src, tgt, rel in edges:
        if papers.get(src, {}).get("title") != "[excluded]" and papers.get(tgt, {}).get("title") != "[excluded]":
            edge_list.append({"source": src, "target": tgt, "relation": rel})

    return {"nodes": nodes, "edges": edge_list}


def main():
    parser = argparse.ArgumentParser(description="Citation Explorer — Radial Paper Discovery")
    subparsers = parser.add_subparsers(dest="cmd", help="Command")

    sp = subparsers.add_parser("explore", help="Explore citation network from a seed paper")
    sp.add_argument("--seed", help="DOI or OpenAlex ID of the seed paper")
    sp.add_argument("--seed-query", help="Search query to find the seed paper")
    sp.add_argument("--depth", type=int, default=2, help="Exploration depth (default: 2)")
    sp.add_argument("--max-papers", type=int, default=30, help="Max papers to collect (default: 30)")
    sp.add_argument("--strategy", choices=["priority", "breadth", "depth"], default="priority")
    sp.add_argument("--min-citations", type=int, default=0, help="Min citation count filter")
    sp.add_argument("--year-from", type=int, default=None, help="Only papers from this year onward")
    sp.add_argument("--focus", nargs="+", default=None,
                    help="Only explore papers matching these terms (e.g. --focus aigc diffusion image generation)")
    sp.add_argument("--exclude-topics", nargs="+", default=None,
                    help="Skip papers matching these terms (e.g. --exclude-topics medical healthcare biology)")
    sp.add_argument("--exclude-visited", help="Path to previous report to exclude already-visited papers")
    sp.add_argument("--output", help="Output Markdown report file")
    sp.add_argument("--json-graph", help="Output JSON citation graph file")
    sp.add_argument("--render-graph", help="Render citation map as interactive HTML (or PNG if path ends in .png)")
    sp.add_argument("--graph-width", type=int, default=1400, help="Graph canvas width (default: 1400)")
    sp.add_argument("--graph-height", type=int, default=900, help="Graph canvas height (default: 900)")

    args = parser.parse_args()

    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    if args.cmd == "explore":
        if not args.seed and not args.seed_query:
            print("Error: provide --seed (DOI/OpenAlex ID) or --seed-query (search terms)")
            sys.exit(1)

        exclude_ids = set()
        if args.exclude_visited:
            exclude_ids = _extract_visited_ids(args.exclude_visited)
            if exclude_ids:
                print(f"📋 Excluding {len(exclude_ids)} previously visited papers")

        explorer = CitationExplorer(
            max_papers=args.max_papers,
            max_depth=args.depth,
            strategy=args.strategy,
            min_citations=args.min_citations,
            year_from=args.year_from,
            focus_terms=args.focus,
            exclude_terms=args.exclude_topics,
        )

        result = explorer.explore(seed=args.seed, seed_query=args.seed_query, exclude_ids=exclude_ids)

        themes = _identify_themes(result["papers"], result["edges"])
        report = generate_report(result, themes)

        if args.output:
            Path(args.output).write_text(report)
            print(f"\n📝 Report saved to {args.output}")
        else:
            print(f"\n{report}")

        theme_graph = generate_theme_graph(result, themes)

        if args.json_graph:
            Path(args.json_graph).write_text(json.dumps(theme_graph, ensure_ascii=False, indent=2))
            print(f"📊 Theme graph saved to {args.json_graph}")

        if args.render_graph:
            _render_path = Path(__file__).parent / "render-graph.py"
            _rg_spec = importlib.util.spec_from_file_location("render_graph", _render_path)
            _rg = importlib.util.module_from_spec(_rg_spec)
            _rg_spec.loader.exec_module(_rg)

            out_path = args.render_graph
            if out_path.endswith(".png"):
                tmp_html = Path(out_path).with_suffix(".tmp.html")
                html_content = _rg.generate_theme_html(theme_graph, width=args.graph_width, height=args.graph_height)
                tmp_html.write_text(html_content)
                _rg.render_png(str(tmp_html), out_path, args.graph_width, args.graph_height)
                tmp_html.unlink(missing_ok=True)
            else:
                html_content = _rg.generate_theme_html(theme_graph, width=args.graph_width, height=args.graph_height)
                Path(out_path).write_text(html_content)
                print(f"📊 Research topic map saved to {out_path}")
                print(f"   Open in browser: file://{Path(out_path).resolve()}")


if __name__ == "__main__":
    main()
