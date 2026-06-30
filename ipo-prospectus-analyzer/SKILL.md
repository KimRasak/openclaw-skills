---
name: ipo-prospectus-analyzer
description: 打新招股书分析工具，辅助IPO打新决策。当用户提到"打新"、"招股书"、"IPO分析"、"新股"、"AH折价"、"港股打新"、"科创板打新"时使用。支持从港交所（HKExnews）、上交所、深交所下载招股书PDF，解析目录，并按估值/基本面/风险/流动性四个维度输出结构化分析报告，含AH折价率计算。
---

# 打新招股书分析

帮助用户分析IPO招股书，输出打新决策所需的结构化分析。

## 执行流程

### 1. 获取招股书

若用户已提供PDF路径，直接进入第2步。

否则，搜索招股书下载链接：
- 港股：从 `https://www.hkexnews.hk` 搜索公司名+招股书
- A股：从上交所/深交所官网搜索
- 使用 `curl -L -o <保存路径> <URL>` 下载PDF

保存至 `/home/gem/workspace/.ark/output/IPO分析_<公司名>_<日期>/招股书.pdf`

### 2. 解析目录

```python
from pypdf import PdfReader
reader = PdfReader("<pdf路径>")
# 提取书签目录
for item in reader.outline:
    page = reader.get_destination_page_number(item) + 1
    print(f"{item.title} ... p{page}")
```

输出目录结构，标注各分析维度对应的章节和页码。

### 3. 按打新决策框架分析

优先级顺序：**财务资料 > 风险因素 > 业务 > 未来计划/募资用途 > 股本 > 行业概览**

提取以下章节内容（使用pdfplumber按页码范围提取）：

```python
import pdfplumber
with pdfplumber.open("<pdf路径>") as pdf:
    text = ""
    for page in pdf.pages[start:end]:  # 按章节页码范围
        text += page.extract_text()
```

**维度一：估值判断**
- 财务资料：收入规模及增速、毛利率、净利率、经营现金流
- 募资用途：主业扩张 vs 补充流动资金

**维度二：基本面**
- 核心产品/服务及竞争壁垒
- 前五大客户收入占比（>50%为集中风险）
- 行业规模与增速、公司市场地位

**维度三：风险排查**
- 风险因素章节中的核心风险（合规/政策/客户集中/核心人员）
- 股权结构是否清晰、控股股东背景

**维度四：流动性**
- 总股本、流通盘大小
- 战略配售/基石投资者锁定期
- 超额配售（绿鞋）机制

### 4. AH折价分析（仅A+H股公司）

若该公司已有A股，必须计算AH溢价率：

```
AH溢价率 = (A股价 ÷ 当日港元汇率 - H股发行价) ÷ H股发行价 × 100%
```

判断标准：
- 溢价率 > 30%：H股性价比高，打新逻辑顺
- 溢价率 10-30%：一般，结合基本面决策
- 溢价率 < 10%：H股估值偏贵，谨慎
- H股溢价A股：高风险，除非有特殊催化剂

### 5. 输出分析报告

见 references/report-template.md 中的报告格式。

## 参考资料

- **报告模板**: 见 references/report-template.md
