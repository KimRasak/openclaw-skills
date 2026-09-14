---
name: academic-api-guide
description: >-
  Query academic literature via arXiv, Semantic Scholar, and OpenAlex APIs
  without API keys, plus Google Scholar via the local browser crawler
  (scholar-crawler). Use when searching papers, fetching metadata, exploring
  citations, filtering by publication year, or building literature review
  tools. Covers endpoint URLs, parameter syntax, year filters, rate limits,
  and recommended usage patterns.
---

# Academic API Guide — arXiv / Semantic Scholar / OpenAlex / Google Scholar

三个免费学术 API 加一个本机 Scholar 爬虫的无 key（或已有 key）用法速查。按场景选择：

| 场景 | 首选 | 备选 |
|---|---|---|
| 关键词搜索 + 筛选 | OpenAlex | S2 bulk search |
| **只看近几年**（避开年代久远的老论文） | Google Scholar：`scholar-crawler --recent 3` | OpenAlex `filter=publication_year:...` |
| 引用链 / 被引分析 | OpenAlex | S2 paper detail；Scholar 引证列表 `--cites` |
| 最新预印本 / 下载 PDF | arXiv | — |
| 单篇详情（tldr、摘要） | S2 paper detail | OpenAlex |

> 年份过滤速记：OpenAlex 用 `filter=publication_year:2023-2025`；S2 用 `year=2023-2025`；
> arXiv 没有原生年份参数（见 §2 的替代做法）；Scholar 用 `--recent 3` 或 `--year-from/--year-to`。

---

## 1. OpenAlex（主力，推荐）

无 key、无速率限制、JSON 返回、字段可选。覆盖 2.5 亿+ 论文。

### 搜索

```bash
curl -s "https://api.openalex.org/works?search=facial+expression+generation&per_page=5&select=id,title,publication_year,cited_by_count,doi"
```

### 常用参数

| 参数 | 说明 | 示例 |
|---|---|---|
| `search` | 全文搜索 | `search=emotion+recognition` |
| `filter` | 精确过滤 | `filter=publication_year:2023-2025,cited_by_count:>10` |
| `sort` | 排序 | `sort=cited_by_count:desc` 或 `sort=publication_date:desc` |
| `per_page` | 每页条数（最大 200） | `per_page=50` |
| `page` | 页码 | `page=2` |
| `select` | 只返回指定字段 | `select=id,title,publication_year,cited_by_count,doi` |

### 按 DOI / OpenAlex ID 查详情

```bash
# DOI
curl -s "https://api.openalex.org/works/doi:10.1109/CVPR.2016.90?select=id,title,publication_year,cited_by_count,referenced_works"

# OpenAlex ID
curl -s "https://api.openalex.org/works/W2964929021?select=id,title,publication_year,cited_by_count"
```

### 获取引用链

```bash
# 被谁引用（cited_by）
curl -s "https://api.openalex.org/works?filter=cites:W2964929021&per_page=10&sort=cited_by_count:desc&select=id,title,publication_year,cited_by_count"

# 引用了谁（references）— 先查 referenced_works 字段拿到 ID 列表
curl -s "https://api.openalex.org/works/W2964929021?select=referenced_works"
```

### Python 示例

```python
import requests

resp = requests.get("https://api.openalex.org/works", params={
    "search": "2D facial expression generation",
    "filter": "publication_year:2022-2025,cited_by_count:>5",
    "sort": "cited_by_count:desc",
    "per_page": 10,
    "select": "id,title,publication_year,cited_by_count,doi",
})
for w in resp.json()["results"]:
    print(f"[{w['publication_year']}] {w['title']}  (cited: {w['cited_by_count']})")
```

### 注意事项

- 建议在 header 带 `mailto`：`requests.get(url, params=params, headers={"mailto": "you@example.com"})`，可获更高速率（polite pool）
- 详细文档：https://docs.openalex.org

---

## 2. arXiv

无 key，免费。唯一能直接获取预印本 PDF 的来源。返回 Atom XML。

### 端点

**必须用 HTTPS**：`https://export.arxiv.org/api/query`（HTTP 会 301 跳转，curl 默认不跟随）

### 搜索

```bash
# curl 加 -L 跟随重定向，或直接用 https
curl -s "https://export.arxiv.org/api/query?search_query=all:facial+expression+generation&start=0&max_results=5"
```

### 查询语法

| 前缀 | 含义 | 示例 |
|---|---|---|
| `all:` | 全字段 | `all:emotion+recognition` |
| `ti:` | 标题 | `ti:diffusion+model` |
| `au:` | 作者 | `au:goodfellow` |
| `abs:` | 摘要 | `abs:facial+animation` |
| `cat:` | 类别 | `cat:cs.CV` |

组合：`AND`、`OR`、`ANDNOT`，如 `ti:expression+AND+cat:cs.CV`

### 排序

```
sortBy=submittedDate&sortOrder=descending
sortBy=relevance&sortOrder=descending
```

### 年份过滤（无原生参数，两种替代）

arXiv API 没有年份参数，只能：

```python
# 1) 推荐：按提交日期排序 + 客户端过滤（最可靠）
import arxiv
client = arxiv.Client()
search = arxiv.Search(query="2D facial expression generation",
                      max_results=50, sort_by=arxiv.SortCriterion.SubmittedDate)
recent = [r for r in client.results(search) if r.published.year >= 2024]
```

```bash
# 2) submittedDate 范围语法（可用但少有人知，写进 search_query）
curl -s "https://export.arxiv.org/api/query?search_query=cat:cs.CV+AND+submittedDate:[202401010000+TO+202512312359]&max_results=5"
```

注意：范围过滤会让"命中的第 1–N 条"整体后移，`max_results` 要放大再过滤，不能只取 5 条。

### Python 示例（推荐用 arxiv 库）

```bash
pip install arxiv
```

```python
import arxiv

client = arxiv.Client()
search = arxiv.Search(
    query="2D facial expression generation",
    max_results=10,
    sort_by=arxiv.SortCriterion.SubmittedDate,
)
for r in client.results(search):
    print(f"[{r.published.date()}] {r.title}")
    print(f"  PDF: {r.pdf_url}")
```

### 按 ID 获取

```bash
curl -s "https://export.arxiv.org/api/query?id_list=2301.12345,2305.67890"
```

### 注意事项

- **速率限制**：请求间隔 ≥ 3 秒，否则可能被临时封禁
- 返回 Atom XML，需解析；`arxiv` Python 库自动处理
- 常见类别：`cs.CV`（视觉）、`cs.AI`（AI）、`cs.LG`（机器学习）、`cs.CL`（NLP）

---

## 3. Semantic Scholar（S2）

搜索 2 亿+ 论文，独有 `tldr` 字段（AI 一句话摘要）。

### API Key 配置

项目 `.env` 文件中已配置 `SEMANTIC_SCHOLAR_API_KEY`。使用时从环境变量读取：

```bash
export $(cat .env | xargs)
curl -s -H "x-api-key: $SEMANTIC_SCHOLAR_API_KEY" "https://api.semanticscholar.org/graph/v1/paper/search?query=emotion&limit=3&fields=title,year"
```

| | 无 Key | 有 Key |
|---|---|---|
| `/paper/search` | 极易 429（~100 req/5min） | **1 req/sec（~300 req/5min）** |
| `/paper/search/bulk` | 可用 | 可用 |
| `/paper/{id}` 详情 | 可用 | 可用 |
| `/paper/{id}/citations` | 可用 | 可用 |
| `/paper/{id}/references` | 可用 | 可用 |

### 搜索

```bash
# 有 key（推荐，速率充裕）
curl -s -H "x-api-key: $SEMANTIC_SCHOLAR_API_KEY" \
  "https://api.semanticscholar.org/graph/v1/paper/search?query=facial+expression+generation&limit=10&fields=title,year,citationCount,tldr"

# 限定年份：year=单年 | 起-止 | 开区间（配合 query 一起传）
curl -s -H "x-api-key: $SEMANTIC_SCHOLAR_API_KEY" \
  "https://api.semanticscholar.org/graph/v1/paper/search?query=facial+expression+generation&year=2023-2026&limit=10&fields=title,year,citationCount"

# 无 key 备选：用 bulk search
curl -s "https://api.semanticscholar.org/graph/v1/paper/search/bulk?query=facial+expression+generation&limit=10&fields=title,year,citationCount,tldr"
```

### 按 ID 查详情

```bash
# arXiv ID
curl -s -H "x-api-key: $SEMANTIC_SCHOLAR_API_KEY" \
  "https://api.semanticscholar.org/graph/v1/paper/ArXiv:2301.12345?fields=title,year,abstract,tldr,citationCount,referenceCount,externalIds"

# DOI
curl -s -H "x-api-key: $SEMANTIC_SCHOLAR_API_KEY" \
  "https://api.semanticscholar.org/graph/v1/paper/DOI:10.1109/CVPR.2016.90?fields=title,year,citationCount,tldr"

# S2 Paper ID
curl -s -H "x-api-key: $SEMANTIC_SCHOLAR_API_KEY" \
  "https://api.semanticscholar.org/graph/v1/paper/204e3073870fae3d05bcbc2f6a8e263d9b72e776?fields=title,year,citationCount"
```

### 引用链

```bash
# 被谁引用
curl -s "https://api.semanticscholar.org/graph/v1/paper/ArXiv:2301.12345/citations?fields=title,year,citationCount&limit=20"

# 引用了谁
curl -s "https://api.semanticscholar.org/graph/v1/paper/ArXiv:2301.12345/references?fields=title,year,citationCount&limit=20"
```

### 常用 fields

`title`, `abstract`, `year`, `venue`, `citationCount`, `referenceCount`, `influentialCitationCount`, `tldr`, `authors`, `authors.name`, `externalIds`, `url`, `openAccessPdf`

### Python 示例

```python
import os, requests
from dotenv import load_dotenv

load_dotenv()  # 从 .env 读取

BASE = "https://api.semanticscholar.org/graph/v1"
API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
headers = {"x-api-key": API_KEY} if API_KEY else {}

resp = requests.get(f"{BASE}/paper/search", headers=headers, params={
    "query": "2D facial expression generation",
    "limit": 10,
    "fields": "title,year,citationCount,tldr,externalIds",
})
for p in resp.json().get("data", []):
    tldr = p.get("tldr") or {}
    print(f"[{p['year']}] {p['title']}  (cited: {p['citationCount']})")
    if tldr.get("text"):
        print(f"  TLDR: {tldr['text']}")
```

### 注意事项

- `.env` 中已有 `SEMANTIC_SCHOLAR_API_KEY`，Python 用 `python-dotenv` 加载，shell 用 `export $(cat .env | xargs)`
- 有 key 时可直接用 `/paper/search`；无 key 时用 `/paper/search/bulk` 替代
- `tldr` 字段是 S2 独有特色，对快速筛选论文非常有用
- 有 key 速率：1 req/sec；请求间仍建议加 100ms 延迟留余量

---

## 4. Google Scholar（本机 scholar-crawler，浏览器爬取）

Scholar 没有官方 API。本机装了 `scholar-crawler`（源码 `/Users/jinzili/code/google-scholar-crawler`）：
真实浏览器访问 scholar.google.com，验证码交给屏幕前的人处理，结果落 JSONL / JSON。

### 年份过滤（只看近几年，避开十年前的经典）

```bash
# 只看最近 3 个日历年（含今年）——搜出来的老论文大多是被引数堆上去的经典
scholar-crawler -q "retrieval augmented generation" --recent 3 -p 2 --json

# 精确区间
scholar-crawler -q "..." --year-from 2023 --year-to 2025 --json

# 引证文献列表同样能限年份（--cites / --cluster 都吃这套过滤）
scholar-crawler --cites 2960712678066186980 --recent 3 --json
```

- `--recent N` 等价于 `--year-from（今年−N+1）`，落在请求上是 `as_ylo`；与 `--year-from` **二选一**，同时给会报错
- 例外：`--author` 主页没有年份过滤（Scholar 限制），抓完用
  `scholar-digest out/author.jsonl --recent 3 -o out/author-recent.jsonl` 补一刀
- 断点/续抓与手写 `--year-from` 完全一致（`--resume` 继续，URL 不变）

### 调用方式（agent）

```bash
scholar-crawler -q "..." --recent 3 -p 2 --json        # stdout 只有一个 JSON 对象，进度在 stderr
scholar-crawler -q "..." --recent 3 --dry-run --json   # 先估价（page_loads / seconds），不发请求
```

- 断点续抓：每页即写即存，`--resume` 从 `out/state.json` 继续
- **验证码只能交给人**：headless 下遇到验证会以 `challenge_unattended` 结束，
  正确做法是让人在窗口里过一次，不要加打码/代理轮换/重试——要批量元数据请改用上面三个 API
- 完整调用约定：`/Users/jinzili/code/google-scholar-crawler/AGENTS.md`

---

## 跨 API 联动模式

三个 API 可通过 **DOI** 和 **arXiv ID** 互查：

```
OpenAlex 搜索 → 拿到 DOI
    ├─→ S2: /paper/DOI:xxx → 获取 tldr
    └─→ arXiv: id_list=xxx → 获取 PDF

arXiv 搜索 → 拿到 arXiv ID
    ├─→ S2: /paper/ArXiv:xxx → 引用链 + tldr
    └─→ OpenAlex: filter=ids.openalex:xxx → 被引数据
```

### Python 联动示例

```python
import requests

def enrich_paper(doi=None, arxiv_id=None):
    """用 S2 补充 tldr，用 arXiv 获取 PDF 链接"""
    result = {}

    if doi:
        s2 = requests.get(
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
            params={"fields": "tldr,openAccessPdf"}
        )
        if s2.ok:
            data = s2.json()
            tldr = data.get("tldr")
            result["tldr"] = tldr.get("text") if tldr else None
            oa = data.get("openAccessPdf")
            result["pdf"] = oa.get("url") if oa else None

    if arxiv_id:
        result["arxiv_pdf"] = f"https://arxiv.org/pdf/{arxiv_id}"
        result["arxiv_abs"] = f"https://arxiv.org/abs/{arxiv_id}"

    return result
```

---

## 相关工具

需要"从种子论文出发、交互式增量扩展引用图"的场景，本机另有独立项目
`/Users/jinzili/code/openalex-literature-graph`（FastAPI + SQLite 持久化，
`python -m backend` 起在 <http://127.0.0.1:8000>），支持标记感兴趣论文以引导后续扩展。
它不是 skill，需要人工在浏览器里操作；agent 自动检索仍用本文档的 API 调用。
