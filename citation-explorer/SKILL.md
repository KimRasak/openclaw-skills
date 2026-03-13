---
name: openclaw-citation-explorer
description: >-
  Explore academic research topics by expanding outward from a seed paper through
  citation chains. Uses OpenAlex API to find referenced/citing papers, prioritizing
  newer and higher-impact works. Use when the user wants to discover related research,
  explore a topic radiating from a paper, build a citation graph, find what a paper
  cites or is cited by, or do breadth-first literature discovery.
---

# Citation Explorer — 以论文为中心的发散式研究发现

从一篇种子论文出发，沿引用链向外层层扩展，发现新的研究方向和重要文献。

## 核心理念

```
种子论文 (Seed)
  ├─→ 引用的论文 (references)  ── 追溯上游基础
  └─→ 被引论文 (cited_by)      ── 探索下游发展
        ├─→ 新论文A → 再展开...
        └─→ 新论文B → 再展开...
```

优先级：**新发表 > 旧发表**，**高引用 > 低引用**，**未访问 > 已访问**

## 快速开始

### 1. 从关键词找到种子论文

```bash
python3 scripts/scholar-search.py search "qwen image text-to-image" --limit 5 --sort citations
```

### 2. 用 DOI 或 OpenAlex ID 启动发散探索（含可视化图谱）

```bash
python3 scripts/citation-explorer.py explore \
  --seed "10.48550/arXiv.2308.12966" \
  --depth 2 \
  --max-papers 30 \
  --strategy priority \
  --focus image vision generation editing multimodal \
  --exclude-topics medical healthcare biology clinical \
  --output exploration.md \
  --render-graph topic_map.html
```

### 3. 以标题搜索定位种子

```bash
python3 scripts/citation-explorer.py explore \
  --seed-query "Qwen-VL A Versatile Vision-Language Model" \
  --depth 2 \
  --max-papers 20 \
  --output exploration.md
```

## 探索策略

### priority（默认，推荐）

优先队列驱动。每层扩展时按 `score = recency * 0.4 + citation_impact * 0.4 + novelty * 0.2` 排序，优先探索高分节点。适合发现重要且前沿的研究。

### breadth

标准 BFS。逐层均匀扩展，不做优先级筛选。适合全面了解引用网络拓扑。

### depth

DFS 风格。沿最高分路径深入探索，适合快速追踪某一特定演化脉络。

## 完整工作流

按以下步骤操作：

### Step 1 — 确定种子论文

用户给出论文标题、DOI、arXiv ID 或关键词。通过搜索确认具体论文：

```bash
python3 scripts/scholar-search.py search "<用户提供的关键词>" --limit 5 --json
```

从结果中让用户确认或自行选取最匹配的论文，记录其 **OpenAlex ID** 或 **DOI**。

### Step 2 — 启动发散探索

```bash
python3 scripts/citation-explorer.py explore \
  --seed "<DOI or OpenAlex ID>" \
  --depth 2 \
  --max-papers 30 \
  --strategy priority \
  --output exploration.md \
  --json-graph graph.json \
  --render-graph citation_map.html
```

参数说明：
- `--depth N` — 从种子向外扩展 N 层（默认 2，建议不超过 3）
- `--max-papers N` — 最多收集 N 篇论文（默认 30）
- `--strategy` — 探索策略：priority / breadth / depth
- `--focus TERM [TERM ...]` — **限定探索范围**：只保留标题或摘要匹配这些词的论文，不匹配的直接跳过不遍历
- `--exclude-topics TERM [TERM ...]` — **排除话题**：标题或摘要匹配这些词的论文直接丢弃
- `--min-citations N` — 过滤掉引用数低于 N 的论文（默认 0）
- `--year-from YYYY` — 只保留该年份之后的论文
- `--output FILE` — 输出 Markdown 报告
- `--json-graph FILE` — 输出研究话题图谱 JSON
- `--render-graph FILE` — 渲染研究话题图谱为交互式 HTML（或 PNG，见下文）
- `--graph-width N` — 图谱画布宽度（默认 1400px）
- `--graph-height N` — 图谱画布高度（默认 900px）

**话题过滤示例**：
- 只看 AIGC 方向：`--focus aigc diffusion image generation editing`
- 排除边缘 AI 应用：`--exclude-topics medical healthcare biology clinical remote-sensing satellite autonomous-driving`
- 两者可组合使用，`--focus` 做白名单，`--exclude-topics` 做黑名单

### Step 3 — 查看研究话题图谱

探索完成后自动生成**研究话题级别的关系图谱** `topic_map.html`：

- **节点 = 研究话题**（如 "Multimodal Understanding"、"Image Editing"、"OCR & Document"）
- **节点大小** = 该话题下包含的论文数量
- **节点圆内数字** = 论文篇数
- **连线粗细** = 两个话题之间的引用关联强度（越粗表示跨话题引用越多）
- **种子话题**（Seed Topic）有白色外圈高亮
- 悬停节点会高亮相关话题，并显示话题下的代表论文列表

也可以单独用 `render-graph.py` 渲染已有的 `graph.json`：

```bash
# 生成交互式 HTML
python3 scripts/render-graph.py graph.json --output topic_map.html

# 生成 PNG 静态图片（需要 pip3 install playwright && python3 -m playwright install chromium）
python3 scripts/render-graph.py graph.json --output topic_map.png --format png --width 1600 --height 1000
```

> **给用户展示图谱的推荐方式**：使用 browser MCP 工具打开生成的 HTML 文件，然后截图返回给用户。
> 或者使用 `--format png` 直接生成 PNG 图片文件。

### Step 4 — 阅读报告并深入

阅读生成的 `exploration.md`，其中包含：
- 按探索层级组织的论文列表（含标题、年份、引用数、摘要）
- 论文间的引用关系
- 发现的研究主题聚类
- 推荐的下一步深入方向

对感兴趣的论文，可进一步获取全文：

```bash
python3 scripts/scholar-search.py deep "<DOI>"
```

### Step 5 — 迭代探索

将 Step 4 中发现的有趣论文作为新种子，重复 Step 2-4。每轮探索会排除已访问的论文。

```bash
python3 scripts/citation-explorer.py explore \
  --seed "<新发现的DOI>" \
  --depth 2 \
  --max-papers 20 \
  --exclude-visited exploration.md \
  --output exploration_round2.md
```

## 输出格式

### Markdown 报告 (exploration.md)

```markdown
# Citation Exploration Report
Seed: "Qwen-VL: A Versatile Vision-Language Model" (2023)

## Layer 0 — Seed
| # | Title | Year | Citations | DOI |
|---|-------|------|-----------|-----|
| 1 | Qwen-VL: A Versatile ... | 2023 | 842 | 10.48550/arXiv.2308.12966 |

## Layer 1 — Direct References & Citing Works
| # | Title | Year | Citations | Relation | DOI |
|---|-------|------|-----------|----------|-----|
| 2 | InstructPix2Pix: Learning to... | 2023 | 1205 | cited_by | ... |
| 3 | LayerDiffuse: Transparent Image... | 2024 | 312 | cited_by | ... |

## Layer 2 — Extended Network
...

## Discovered Themes
1. **图像编辑 (Image Editing)** — papers 2, 7, 12
2. **图层分离 (Layer Decomposition)** — papers 3, 15
3. **多模态理解 (Multimodal Understanding)** — papers 4, 8, 11

## Suggested Next Seeds
- "LayerDiffuse" (paper 3) — 图层生成新方向，值得深入
- "InstructPix2Pix" (paper 2) — 指令驱动编辑的奠基工作
```

### 研究话题图谱 (graph.json)

```json
{
  "type": "theme_graph",
  "seed_title": "Qwen-VL: A Versatile Vision-Language Model...",
  "nodes": [
    {"id": "Multimodal Understanding", "name": "Multimodal Understanding",
     "paper_count": 13, "total_citations": 6110, "median_year": 2023,
     "layer": 0, "is_seed_topic": true,
     "paper_titles": ["Qwen-VL...", "MMMU...", "..."]}
  ],
  "edges": [
    {"source": "Large Language Models", "target": "Multimodal Understanding", "weight": 23},
    {"source": "Medical & Healthcare", "target": "Multimodal Understanding", "weight": 8}
  ]
}
```

节点 = 研究话题，边 weight = 两个话题之间跨话题论文引用的次数。

## 注意事项

- OpenAlex API 免费，无需 API key，但请遵守合理速率（脚本内置 100ms 间隔）
- `--depth 3` 以上会产生大量 API 调用，建议配合 `--max-papers` 控制规模
- 缓存保存在 `/tmp/citation_explorer_cache/`，重复探索不会重复请求
- 如遇网络问题，脚本支持自动重试（3 次）

## 附加资源

- 搜索脚本详细用法见 [scripts/scholar-search.py](scripts/scholar-search.py)
- 探索引擎详细用法见 [scripts/citation-explorer.py](scripts/citation-explorer.py)
- 图谱渲染器详细用法见 [scripts/render-graph.py](scripts/render-graph.py)
