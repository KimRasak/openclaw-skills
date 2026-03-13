#!/usr/bin/env python3
"""
Research Topic Map Visualizer — 将研究话题图谱渲染为交互式 HTML 或静态 PNG。

节点 = 研究话题（如"Image Editing"、"Multimodal Understanding"），
边 = 话题之间通过论文引用产生的关联，边越粗关联越紧密。

Usage:
  python3 render-graph.py graph.json --output topic_map.html
  python3 render-graph.py graph.json --output topic_map.png --format png
"""
import argparse
import json
import math
import sys
from pathlib import Path

TOPIC_PALETTE = [
    "#FF6B35",  # warm orange
    "#3A86FF",  # electric blue
    "#8338EC",  # vivid purple
    "#06D6A0",  # emerald teal
    "#FFD166",  # amber gold
    "#EF476F",  # raspberry pink
    "#118AB2",  # cerulean
    "#073B4C",  # dark teal
    "#F77F00",  # tangerine
    "#7209B7",  # deep violet
    "#4CC9F0",  # sky cyan
    "#E63946",  # crimson
    "#2A9D8F",  # ocean green
    "#264653",  # charcoal blue
    "#E9C46A",  # sandy gold
]


def generate_theme_html(graph: dict, width: int = 1400, height: int = 900) -> str:
    """Generate interactive HTML for a research-topic-level graph."""
    nodes = graph["nodes"]
    edges = graph["edges"]
    seed_title = graph.get("seed_title", "")
    seed_year = graph.get("seed_year", "")

    if len(seed_title) > 55:
        seed_title = seed_title[:55] + "..."
    title = f"Research Topic Map"
    subtitle_text = f"Seed: {seed_title} ({seed_year})" if seed_title else ""

    max_papers = max((n.get("paper_count", 1) for n in nodes), default=1) or 1
    max_citations = max((n.get("total_citations", 0) for n in nodes), default=1) or 1
    max_edge_weight = max((e.get("weight", 1) for e in edges), default=1) or 1

    nodes_json = json.dumps(nodes, ensure_ascii=False)
    edges_json = json.dumps(edges, ensure_ascii=False)
    palette_json = json.dumps(TOPIC_PALETTE)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    font-family: 'Space Grotesk', sans-serif;
    background: #0B0E17;
    color: #E2E8F0;
    overflow: hidden;
  }}

  #graph-container {{
    width: 100vw;
    height: 100vh;
    position: relative;
    background:
      radial-gradient(ellipse at 30% 40%, rgba(56, 56, 236, 0.06) 0%, transparent 60%),
      radial-gradient(ellipse at 70% 60%, rgba(236, 56, 120, 0.04) 0%, transparent 60%),
      #0B0E17;
  }}

  svg {{ width: 100%; height: 100%; }}

  .header {{
    position: absolute;
    top: 24px;
    left: 28px;
    z-index: 10;
    pointer-events: none;
  }}

  .header h1 {{
    font-size: 22px;
    font-weight: 700;
    color: #F1F5F9;
    letter-spacing: -0.5px;
  }}

  .header .seed-info {{
    font-size: 12px;
    color: #64748B;
    margin-top: 5px;
    font-family: 'IBM Plex Mono', monospace;
    max-width: 500px;
  }}

  .header .stats {{
    font-size: 11px;
    color: #475569;
    margin-top: 3px;
    font-family: 'IBM Plex Mono', monospace;
  }}

  .tooltip {{
    position: absolute;
    pointer-events: none;
    background: #1A1F2E;
    border: 1px solid #2D3548;
    border-radius: 10px;
    padding: 14px 18px;
    font-size: 12px;
    line-height: 1.6;
    max-width: 400px;
    box-shadow: 0 12px 40px rgba(0,0,0,0.6);
    opacity: 0;
    transition: opacity 0.15s;
    z-index: 100;
  }}

  .tooltip .tt-name {{
    font-weight: 700;
    font-size: 15px;
    color: #F1F5F9;
    margin-bottom: 8px;
  }}

  .tooltip .tt-stats {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    color: #94A3B8;
    margin-bottom: 8px;
  }}

  .tooltip .tt-stats span {{
    color: #CBD5E1;
    font-weight: 500;
  }}

  .tooltip .tt-papers {{
    font-size: 11px;
    color: #64748B;
    border-top: 1px solid #2D3548;
    padding-top: 8px;
    margin-top: 4px;
  }}

  .tooltip .tt-papers li {{
    margin: 3px 0;
    color: #94A3B8;
    list-style: none;
    padding-left: 10px;
    position: relative;
  }}

  .tooltip .tt-papers li::before {{
    content: "\\25B8";
    position: absolute;
    left: 0;
    color: #475569;
  }}

  .legend {{
    position: absolute;
    bottom: 20px;
    left: 28px;
    z-index: 10;
    pointer-events: none;
  }}

  .legend .legend-label {{
    font-size: 10px;
    color: #475569;
    font-family: 'IBM Plex Mono', monospace;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 6px;
  }}

  .legend .legend-row {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 4px;
  }}

  .legend .l-circle {{
    border-radius: 50%;
    flex-shrink: 0;
  }}

  .legend .l-text {{
    font-size: 11px;
    color: #64748B;
    font-family: 'IBM Plex Mono', monospace;
  }}

  .node-label {{
    font-family: 'Space Grotesk', sans-serif;
    fill: #E2E8F0;
    font-weight: 600;
    pointer-events: none;
    text-shadow: 0 2px 6px rgba(0,0,0,0.9), 0 0 12px rgba(0,0,0,0.7);
  }}

  .node-count {{
    font-family: 'IBM Plex Mono', monospace;
    fill: #64748B;
    font-size: 10px;
    font-weight: 400;
    pointer-events: none;
  }}
</style>
</head>
<body>

<div id="graph-container">
  <div class="header">
    <h1>{title}</h1>
    <div class="seed-info">{subtitle_text}</div>
    <div class="stats">{len(nodes)} topics &middot; {len(edges)} connections &middot; {sum(n.get('paper_count',0) for n in nodes)} papers total</div>
  </div>

  <div class="legend">
    <div class="legend-label">node size = paper count</div>
    <div class="legend-row">
      <div class="l-circle" style="width:12px;height:12px;border:2px solid #475569;"></div>
      <div class="l-text">1 paper</div>
      <div class="l-circle" style="width:28px;height:28px;border:2px solid #475569;margin-left:12px;"></div>
      <div class="l-text">{max_papers}+ papers</div>
    </div>
    <div class="legend-label" style="margin-top:8px;">edge width = citation flow</div>
  </div>

  <div class="tooltip" id="tooltip"></div>

  <svg id="graph-svg"></svg>
</div>

<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<script>
(function() {{
  const rawNodes = {nodes_json};
  const rawEdges = {edges_json};
  const palette = {palette_json};
  const maxPapers = {max_papers};
  const maxCit = {max_citations};
  const maxEdgeW = {max_edge_weight};

  const container = document.getElementById("graph-container");
  const W = container.clientWidth;
  const H = container.clientHeight;

  const idMap = {{}};
  const nodes = rawNodes.map((n, i) => {{
    const obj = {{ ...n, index: i, color: palette[i % palette.length] }};
    idMap[n.id] = obj;
    return obj;
  }});

  // Pre-position: seed topics near center, others radially outward
  nodes.forEach((n, i) => {{
    if (n.is_seed_topic) {{
      n.x = W / 2 + (Math.random() - 0.5) * 60;
      n.y = H / 2 + (Math.random() - 0.5) * 60;
    }} else {{
      const angle = (2 * Math.PI * i) / Math.max(nodes.length, 1) + Math.random() * 0.3;
      const radius = 150 + (n.layer || 1) * 80 + Math.random() * 40;
      n.x = W / 2 + Math.cos(angle) * radius;
      n.y = H / 2 + Math.sin(angle) * radius;
    }}
  }});

  const links = rawEdges
    .filter(e => idMap[e.source] && idMap[e.target])
    .map(e => ({{ source: idMap[e.source], target: idMap[e.target], weight: e.weight || 1 }}));

  const svg = d3.select("#graph-svg").attr("width", W).attr("height", H);
  const g = svg.append("g");

  // zoom
  svg.call(d3.zoom().scaleExtent([0.3, 4])
    .on("zoom", (event) => g.attr("transform", event.transform)));

  // glow filter
  const defs = svg.append("defs");
  const glowFilter = defs.append("filter").attr("id", "topic-glow").attr("x", "-50%").attr("y", "-50%").attr("width", "200%").attr("height", "200%");
  glowFilter.append("feGaussianBlur").attr("in", "SourceGraphic").attr("stdDeviation", "6").attr("result", "blur");
  const merge = glowFilter.append("feMerge");
  merge.append("feMergeNode").attr("in", "blur");
  merge.append("feMergeNode").attr("in", "SourceGraphic");

  function nodeRadius(d) {{
    return 16 + Math.sqrt(d.paper_count / maxPapers) * 28;
  }}

  function edgeWidth(d) {{
    return 1.5 + (d.weight / maxEdgeW) * 6;
  }}

  // edges
  const link = g.append("g")
    .selectAll("line")
    .data(links)
    .enter().append("line")
    .attr("stroke", "#334155")
    .attr("stroke-opacity", 0.5)
    .attr("stroke-width", edgeWidth)
    .attr("stroke-linecap", "round");

  // node groups
  const nodeG = g.append("g")
    .selectAll("g")
    .data(nodes)
    .enter().append("g")
    .attr("cursor", "pointer")
    .call(d3.drag()
      .on("start", dragStart)
      .on("drag", dragging)
      .on("end", dragEnd));

  // outer glow ring for seed topics
  nodeG.filter(d => d.is_seed_topic)
    .append("circle")
    .attr("r", d => nodeRadius(d) + 6)
    .attr("fill", "none")
    .attr("stroke", d => d.color)
    .attr("stroke-width", 2)
    .attr("stroke-opacity", 0.3)
    .style("filter", "url(#topic-glow)");

  // main circle
  nodeG.append("circle")
    .attr("r", nodeRadius)
    .attr("fill", d => d.color)
    .attr("fill-opacity", 0.85)
    .attr("stroke", d => d.is_seed_topic ? "#FFF" : d.color)
    .attr("stroke-width", d => d.is_seed_topic ? 2.5 : 1)
    .attr("stroke-opacity", d => d.is_seed_topic ? 0.9 : 0.3);

  // topic name labels
  nodeG.append("text")
    .attr("class", "node-label")
    .attr("text-anchor", "middle")
    .attr("dy", d => -nodeRadius(d) - 10)
    .attr("font-size", d => d.is_seed_topic ? "13px" : "11px")
    .text(d => d.name);

  // paper count inside node
  nodeG.append("text")
    .attr("class", "node-count")
    .attr("text-anchor", "middle")
    .attr("dy", 4)
    .attr("fill", "#FFF")
    .attr("font-size", d => nodeRadius(d) > 25 ? "12px" : "10px")
    .attr("opacity", 0.8)
    .text(d => d.paper_count);

  // tooltip
  const tooltip = document.getElementById("tooltip");

  nodeG.on("mouseover", (event, d) => {{
    const papersHtml = (d.paper_titles || [])
      .filter(t => t)
      .slice(0, 5)
      .map(t => `<li>${{t.length > 60 ? t.slice(0, 60) + "..." : t}}</li>`)
      .join("");

    tooltip.innerHTML = `
      <div class="tt-name" style="color:${{d.color}}">${{d.name}}</div>
      <div class="tt-stats">
        Papers: <span>${{d.paper_count}}</span> &middot;
        Total citations: <span>${{(d.total_citations || 0).toLocaleString()}}</span><br>
        Median year: <span>${{d.median_year || "N/A"}}</span> &middot;
        Discovery layer: <span>${{d.layer}}</span>
        ${{d.is_seed_topic ? ' &middot; <span style="color:#FF6B35">SEED TOPIC</span>' : ''}}
      </div>
      ${{papersHtml ? `<div class="tt-papers"><ul>${{papersHtml}}</ul></div>` : ''}}
    `;
    tooltip.style.opacity = 1;

    // highlight connected topics
    const connectedIds = new Set();
    connectedIds.add(d.id);
    links.forEach(l => {{
      if (l.source === d) connectedIds.add(l.target.id);
      if (l.target === d) connectedIds.add(l.source.id);
    }});

    link.attr("stroke-opacity", l =>
      l.source === d || l.target === d ? 0.8 : 0.08
    ).attr("stroke", l =>
      l.source === d || l.target === d ? d.color : "#334155"
    );

    nodeG.attr("opacity", n => connectedIds.has(n.id) ? 1 : 0.15);
  }})
  .on("mousemove", (event) => {{
    const rect = container.getBoundingClientRect();
    tooltip.style.left = (event.clientX - rect.left + 16) + "px";
    tooltip.style.top = (event.clientY - rect.top - 10) + "px";
  }})
  .on("mouseout", () => {{
    tooltip.style.opacity = 0;
    link.attr("stroke-opacity", 0.5).attr("stroke", "#334155");
    nodeG.attr("opacity", 1);
  }});

  // force simulation
  const simulation = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(links).id(d => d.id).distance(d => 160 - d.weight * 8).strength(d => 0.3 + d.weight / maxEdgeW * 0.4))
    .force("charge", d3.forceManyBody().strength(d => -200 - d.paper_count * 30))
    .force("center", d3.forceCenter(W / 2, H / 2))
    .force("collision", d3.forceCollide().radius(d => nodeRadius(d) + 20))
    .force("x", d3.forceX(W / 2).strength(0.035))
    .force("y", d3.forceY(H / 2).strength(0.035))
    .on("tick", () => {{
      link
        .attr("x1", d => d.source.x)
        .attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x)
        .attr("y2", d => d.target.y);
      nodeG.attr("transform", d => `translate(${{d.x}},${{d.y}})`);
    }});

  function dragStart(event, d) {{
    if (!event.active) simulation.alphaTarget(0.3).restart();
    d.fx = d.x; d.fy = d.y;
  }}
  function dragging(event, d) {{ d.fx = event.x; d.fy = event.y; }}
  function dragEnd(event, d) {{
    if (!event.active) simulation.alphaTarget(0);
    d.fx = null; d.fy = null;
  }}

}})();
</script>
</body>
</html>"""
    return html


def render_png(html_path: str, png_path: str, width: int, height: int):
    """Render HTML to PNG using Playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Error: PNG rendering requires playwright.")
        print("Install with: pip3 install playwright && python3 -m playwright install chromium")
        sys.exit(1)

    abs_html = str(Path(html_path).resolve())

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        page.goto(f"file://{abs_html}")
        page.wait_for_timeout(3500)
        page.screenshot(path=png_path, full_page=False)
        browser.close()

    print(f"🖼️  PNG saved to {png_path}")


def main():
    parser = argparse.ArgumentParser(description="Render research topic map as interactive HTML or PNG")
    parser.add_argument("input", help="Path to graph.json (theme_graph output of citation-explorer.py)")
    parser.add_argument("--output", "-o", default="topic_map.html", help="Output file (default: topic_map.html)")
    parser.add_argument("--format", "-f", choices=["html", "png"], default=None,
                        help="Output format. Auto-detected from extension if omitted.")
    parser.add_argument("--width", type=int, default=1400, help="Canvas width (default: 1400)")
    parser.add_argument("--height", type=int, default=900, help="Canvas height (default: 900)")

    args = parser.parse_args()

    graph_path = Path(args.input)
    if not graph_path.exists():
        print(f"Error: {args.input} not found")
        sys.exit(1)

    graph = json.loads(graph_path.read_text())

    if not graph.get("nodes"):
        print("Error: graph contains no nodes")
        sys.exit(1)

    fmt = args.format
    if fmt is None:
        fmt = "png" if args.output.endswith(".png") else "html"

    html_content = generate_theme_html(graph, width=args.width, height=args.height)

    if fmt == "html":
        Path(args.output).write_text(html_content)
        print(f"📊 Interactive topic map saved to {args.output}")
        print(f"   Open in browser: file://{Path(args.output).resolve()}")
    elif fmt == "png":
        tmp_html = Path(args.output).with_suffix(".tmp.html")
        tmp_html.write_text(html_content)
        render_png(str(tmp_html), args.output, args.width, args.height)
        tmp_html.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
