# TOOLS.md — AI Autopilot

## 论文搜索信息源（按优先级排序）

### ✅ 主力源（每次搜索必用）

| 来源 | API | 覆盖范围 | 限制 |
|---|---|---|---|
| **arXiv** | `https://export.arxiv.org/api/query` | CS/AI/数学/物理预印本，AIGC 论文最集中 | 免费，无需 key，3 req/s |
| **Semantic Scholar** | `https://api.semanticscholar.org/graph/v1/paper/search` | 跨学科 2 亿+篇，含引文网络 | 免费 tier 有速率限制，建议申请 API key |

### ⚙️ 辅助源（特定场景使用）

| 来源 | API | 何时使用 | 限制 |
|---|---|---|---|
| **PubMed** | NCBI E-utilities | 生物医学/临床研究专题 | 免费，3 req/s (无 key) |
| **Google Scholar** | 无官方 API，需 scrape | 最广泛覆盖，但难以程序化访问 | ❌ 直接访问返回 403，需 SerpAPI 等付费代理 |
| **IEEE Xplore** | 需 API key | 工程/CS 期刊和会议 | 需申请开发者账号 |
| **ACM Digital Library** | 无公开 API | CS 核心会议/期刊 | ❌ 无法程序化访问 |
| **Scopus / Web of Science** | 需机构订阅 | 综合学术数据库 | ❌ 需付费/机构账号 |
| **Unpaywall** | `https://api.unpaywall.org/v2/DOI?email=` | 查找免费全文 | 需邮箱，配合 DOI 使用 |
| **ChEMBL** | REST API | 仅药理学/化合物活性数据 | 免费 |

### 🔍 默认搜索策略

1. **CS/AI/技术类话题** → arXiv（主）+ Semantic Scholar（补充 + 引文追踪）
2. **生物医学/临床类话题** → PubMed（主）+ Semantic Scholar（引文追踪）
3. **跨学科/不确定** → Semantic Scholar（主）+ arXiv + PubMed
4. **任何话题** → 对高分论文用 Unpaywall 找全文

### 📋 搜索流程

对每次搜索：
1. 根据话题选择信息源组合
2. 先搜主力源，获取初始结果
3. 用 Semantic Scholar 做引文网络追踪（forward + backward）
4. 去重合并结果
5. 评分筛选

## Rate Limiting Notes

- arXiv: 3 req/s，建议间隔 500ms
- Semantic Scholar (free tier): ~100 req/5min，遇 429 等 5s 重试
- PubMed (no API key): 3 req/s
- PubMed (with API key): 10 req/s
- Parallel subagents: delay = (num_parallel / rate_limit) + safety_margin
- HTTP 429 recovery: wait 5s, double delay, retry

## Unpaywall

- Requires user email for API access (set in USER.md or ask on first use)
- No authentication needed beyond email
- Priority: published OA > repository > preprint > author manuscript

## 待配置

- [ ] Semantic Scholar API key（提高速率限制）
- [ ] Google Scholar 代理方案（SerpAPI / ScraperAPI）
- [ ] IEEE Xplore API key
- [ ] Unpaywall email（在 USER.md 中设置）
