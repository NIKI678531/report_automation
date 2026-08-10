# DA-Report SQLite 数据库说明

面向下游项目的只读数据快照,由生产 MySQL 库 `da_report` 的 mysqldump 转换而来。

| 项 | 值 |
| --- | --- |
| 文件 | `da_report.sqlite`(约 176 MB) |
| 来源 | `dump-da_report-202608071123-2.sql`(生产 RDS,2026-08-07 11:23 导出) |
| 编码 | UTF-8;中文内容为**繁体中文** |
| 转换脚本 | `scripts/mysqldump_to_sqlite.py`(DA-Report 仓库) |

重新生成:

```bash
uv run python scripts/mysqldump_to_sqlite.py dump-da_report-202608071123-2.sql da_report.sqlite
```

---

## 1. 数据总览

| 表 | 行数 | 说明 |
| --- | ---: | --- |
| `news_sources` | 32 | 新闻源配置(RSS / HTML / API) |
| `news_items` | 76,157 | 抓取到的原始新闻条目 |
| `news_enrichments` | 76,157 | AI 加工结果:双语标题/摘要 + 分类 + 情绪 + 重要性 |
| `market_instruments` | 29 | 行情标的定义(指数、个股、汇率、收益率、商品) |
| `market_snapshots` | 1,536 | 每标的每日行情快照(65 个交易日) |
| `csop_products` | 18 | 报告中展示的南方东英产品清单 |
| `holding_constituents` | 696 | 各 ETF 的成分股快照 |
| `report_drafts` | 205 | 已生成的报告(草稿/定稿) |
| `report_items` | 1,037 | 报告中实际选用的新闻条目 |

数据覆盖区间:

- 新闻 `published_at`:主要集中在 2026-05 ~ 2026-08-07(少量源会回带历史文章,最早到 2005 年)
- 行情 `as_of_date`:2026-05-08 ~ 2026-08-06(DA);2026-06-01 ~ 2026-08-06(Regional)

> **`report_type` 是贯穿全库的核心维度**,取值 `da`(数字资产日报)或 `regional`(区域市场晨报)。`news_sources`、`market_instruments`、`csop_products`、`report_drafts` 都带这个字段,取数时务必先按它过滤。

---

## 2. 表结构

### 2.1 `news_sources` — 新闻源

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER PK | |
| `code` | TEXT UNIQUE | 源代码,如 `coindesk`、`zawya` |
| `name_en` / `name_zh` | TEXT | 显示名 |
| `kind` | TEXT | `rss` / `html` / `api` |
| `url` | TEXT | 抓取地址 |
| `language` | TEXT | `en` / `zh` / `ko` |
| `is_active` | INTEGER | 1 = 仍在抓取 |
| `report_type` | TEXT | `da` / `regional`,各 16 个 |
| `created_at` | TEXT | |

条目数 Top 源:ChainCatcher (11,157)、PANews (7,975)、Zawya (7,836)、Arab News Business (7,593)、Reuters World (6,123)。

部分 Google News 代理源(`code` 带 `_google` 后缀)的 `url` 字段是 Google RSS 搜索串,`news_items.url` 已解码为原始文章链接。

### 2.2 `news_items` — 原始新闻

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER PK | |
| `source_id` | INTEGER FK → `news_sources.id` | |
| `url_hash` | TEXT UNIQUE | 规范化 URL 的 sha256,去重键 |
| `url` | TEXT | 文章链接 |
| `title_raw` | TEXT | 原始标题(未翻译) |
| `summary_raw` | TEXT | RSS 摘要 / 正文片段,可能为 NULL,部分条目是全文 |
| `published_at` | TEXT | 发布时间(UTC,`YYYY-MM-DD HH:MM:SS`),可能为 NULL |
| `language` | TEXT | 原文语言 |
| `fetched_at` | TEXT | 入库时间 |

### 2.3 `news_enrichments` — AI 加工结果 ★

与 `news_items` **一对一**(`news_item_id` UNIQUE)。已核对:本快照中不存在缺少 enrichment 的新闻,可以放心用 INNER JOIN。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER PK | |
| `news_item_id` | INTEGER UNIQUE FK → `news_items.id` | |
| `title_en` / `title_zh` | TEXT | 双语标题(繁体) |
| `summary_zh` | TEXT | 中文摘要 |
| `summary_en` | TEXT | 英文摘要;仅 regional 报告生成,DA 为 NULL |
| `category` | TEXT | 见下表 |
| `region` | TEXT | 仅 regional 有值,DA 为 NULL |
| `sentiment` | TEXT | `bull` / `bear` / `neutral` |
| `score` | REAL | 情绪强度 |
| `importance_score` | REAL | 重要性 0–100,默认 50,用于排序筛选 |
| `model` | TEXT | 生成模型;本快照全部为 `gpt-5.4` |
| `created_at` | TEXT | |

**`category` 分布**(DA 与 regional 共用字段,但取值集合不同):

| category | 行数 | 归属 |
| --- | ---: | --- |
| `Market` | 36,180 | 两者共用 |
| `Crypto-related` | 11,101 | DA |
| `Other` | 9,126 | 两者共用(未命中分类的兜底) |
| `View` | 6,272 | DA |
| `Policy` | 5,600 | DA |
| `Institutional` | 2,926 | DA |
| `Corporate` | 2,296 | **Regional 公司新闻** |
| `Tokenization` | 1,443 | DA |
| `MSTR` | 684 | DA |
| `COIN` | 529 | DA |

**`region` 分布**:Saudi Arabia (6,056)、Southeast Asia (5,058)、Korea (4,133)、US (3,518)、China (2,157)、Japan (1,651)、Taiwan (198)、Vietnam (168);NULL 53,218(基本是 DA 新闻)。

> ⚠️ **关于公司新闻**:`category = 'Corporate'` 是经过成分股校验后的结果 —— 只有 AI 识别出的主体公司确实在某只 ETF 的 `holding_constituents` 里,才会保留为 `Corporate`,否则降级为 `Other`。所以这 2,296 条是"与我们持仓相关的公司新闻",而非泛指的公司新闻。

### 2.4 `market_instruments` — 行情标的

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER PK | |
| `code` | TEXT UNIQUE | 内部代码;regional 标的统一 `R_` 前缀 |
| `display_en` / `display_zh` | TEXT | 表格显示名 |
| `category` | TEXT | `crypto` / `futures` / `equity` / `index` / `fx` / `commodity` / `bond` / `yield` |
| `source` | TEXT | 目前全部为 `bloomberg` |
| `source_symbol` | TEXT | Bloomberg ticker,如 `SPX Index` |
| `sort_order` | INTEGER | 表内展示顺序 |
| `is_active` | INTEGER | |
| `report_type` | TEXT | `da`(10 个)/ `regional`(19 个) |

DA 标的:BTC/ETH 现货与期货、S&P 500、纳斯达克综指、MSTR、COIN、美元指数、黄金。
Regional 标的:纳指 100、日经 225、富时沙特、富时越南 30、恒生科技、恒指、沪深 300、KOSPI 200、富时亚太低碳、新交所泛东南亚科技、美债 20Y+ 指数、10/20/30 年美债收益率、以及港元兑日圆/人民币/里亚尔/越南盾等汇率。

### 2.5 `market_snapshots` — 行情快照 ★

唯一约束 `(instrument_id, as_of_date)`,每标的每日一行。

| 字段 | 类型 | 非空率 | 说明 |
| --- | --- | ---: | --- |
| `id` | INTEGER PK | | |
| `instrument_id` | INTEGER FK → `market_instruments.id` | | |
| `as_of_date` | TEXT | | 数据日期 `YYYY-MM-DD` |
| `last_price` | REAL | 100% | 收盘价;`yield` 类标的存的是收益率数值(如 `4.6778` 即 4.68%) |
| `daily_return_pct` | REAL | 100% | 日涨跌幅 |
| `weekly_return_pct` | REAL | 93% | 近 7 日 |
| `ytd_return_pct` | REAL | 93% | 年初至今 |
| `month1_return_pct` | REAL | 90% | 近 1 个月 |
| `month3_return_pct` | REAL | 90% | 近 3 个月 |
| `month6_return_pct` | REAL | 90% | 近 6 个月 |
| `fetched_at` | TEXT | | 抓取时间 |

> ⚠️ **`*_return_pct` 的单位取决于标的类别,这是最容易踩的坑:**
>
> - 普通标的(`equity` / `index` / `fx` / `bond` / `crypto` / `futures` / `commodity`):**百分比数值**,`1.35` = +1.35%,已 ×100,不要再乘。
> - `category = 'yield'` 的三只美债收益率(`R_UST10Y` / `R_UST20Y` / `R_UST30Y`):这几列存的是**基点变化(bps)**,计算方式为 `(今值 - 基准值) × 100`。例如 2026-08-06 `R_UST10Y` 的 `last_price = 4.6778`、`daily_return_pct = 6.51`,含义是收益率 4.68%、当日上行 6.51 个基点 —— 不是涨了 6.51%。
>
> 月度 / YTD 字段是后期新增的,较早日期为 NULL。Bloomberg 取不到数时会写入 `last_price = NULL` 的占位行(本快照中无此情况)。

### 2.6 `csop_products` — 产品清单

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER PK | |
| `group_label_en` / `group_label_zh` | TEXT | 分组标签,渲染时同组合并单元格 |
| `ticker_en` / `ticker_zh` | TEXT | 代码,如 `3066.HK`、`7711.HK / 9711.HK` |
| `name_en` / `name_zh` | TEXT | 产品全称 |
| `sort_order` | INTEGER | |
| `is_active` | INTEGER | |
| `report_type` | TEXT | `da`(8 个)/ `regional`(10 个) |
| `trader_code` | TEXT | CSOP 内部基金代码,如 `HK-SAU`;关联 `holding_constituents.trader_code`。DA 产品为 NULL |

⚠️ `3121.HK`(KOSPI 200 ETF)的 `trader_code` 是**空字符串 `''` 而非 NULL**,做 JOIN 时注意用 `NULLIF(trader_code, '')` 或 `trader_code <> ''` 过滤。

### 2.7 `holding_constituents` — ETF 成分股

**注意:这张表没有外键约束到 `csop_products`,靠 `trader_code` 字符串关联。** 每次 ETL 会全量替换某个 `trader_code` 下的所有行,所以表里只有各基金的最新一期持仓。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER PK | |
| `trader_code` | TEXT | 基金代码 |
| `trade_date` | TEXT | 持仓日期 |
| `name_zh` / `name_en` | TEXT | 证券名称 |
| `ticker` | TEXT | Bloomberg ticker,如 `981 HK EQUITY` |
| `oms_sec_id` | TEXT | OMS 代码,如 `981 HK` |
| `country` | TEXT | |
| `weight` | REAL | 权重(百分比数值) |
| `updated_at` | TEXT | |

| trader_code | 成分股数 | 最新持仓日 |
| --- | ---: | --- |
| `HK-NIK225`(日经 225) | 225 | 2026-07-16 |
| `SG-ALC`(富时亚太精选) | 199 | 2026-08-06 |
| `HK-METAV`(纳指 100) | 102 | 2026-06-29 |
| `HK-SAU`(沙特) | 64 | 2026-07-23 |
| `SG-ATECH`(泛东南亚科技) | 30 | 2026-08-05 |
| `HK-VN30`(越南 30) | 29 | 2026-08-06 |
| `HK-CFTC`(亚洲科技) | 20 | 2026-06-30 |
| `HK-CKTH`(港韩科技+) | 20 | 2026-06-30 |
| `HK-CMA7`(MAG Seven) | 7 | 2026-06-29 |

> `HK-CFTC` / `HK-CKTH` 只有 20 行,是数据仓库只提供 Top-N 持仓,并非完整成分。

### 2.8 `report_drafts` / `report_items` — 已发布报告

`report_drafts` 一行一份报告(`report_date` + `report_type` + `cadence`)。本快照中 205 份全部为 `status = 'draft'`:DA 日报 111 / DA 周报 21 / Regional 日报 57 / Regional 周报 16。`cadence` 取 `daily` / `weekly`。

`report_items` 是报告实际选用的条目:`news_item_id` 指向原新闻(13 行为 NULL,表示人工添加的链接),`section` 是版块(323 行为 NULL),`title_en/zh`、`summary_en/zh`、`url`、`region` 是**发布时定稿的文案快照**(可能被编辑过,与 `news_enrichments` 里的 AI 原稿不同)。

`section` 分布:Market 340、Corporate 157、View 61、MSTR 48、Policy 38、Institutional 38、COIN 15、Tokenization 8、Crypto-related 8、Other 1。

> 若需要"经人工筛选认可的新闻",用 `report_items` 而不是全量 `news_enrichments`。

---

## 3. 常用查询

**公司新闻(regional,带来源与区域)**

```sql
SELECT i.published_at, e.region, e.title_zh, e.title_en, e.summary_zh,
       e.sentiment, e.importance_score, i.url, s.name_en AS source
FROM news_enrichments e
JOIN news_items   i ON i.id = e.news_item_id
JOIN news_sources s ON s.id = i.source_id
WHERE e.category = 'Corporate'
  AND s.report_type = 'regional'
  AND i.published_at >= '2026-07-01'
ORDER BY i.published_at DESC;
```

**某日全部行情表现**

```sql
SELECT m.code, m.display_en, m.display_zh, m.category,
       s.last_price, s.daily_return_pct, s.weekly_return_pct,
       s.month1_return_pct, s.month3_return_pct, s.month6_return_pct, s.ytd_return_pct
FROM market_snapshots s
JOIN market_instruments m ON m.id = s.instrument_id
WHERE s.as_of_date = '2026-08-06' AND m.report_type = 'regional'
ORDER BY m.sort_order;
```

**单一指数的历史序列**

```sql
SELECT s.as_of_date, s.last_price, s.daily_return_pct
FROM market_snapshots s
JOIN market_instruments m ON m.id = s.instrument_id
WHERE m.code = 'R_NKY'
ORDER BY s.as_of_date;
```

**产品 → 成分股**

```sql
SELECT p.ticker_en, p.name_en, h.name_en AS holding, h.ticker, h.weight, h.trade_date
FROM csop_products p
JOIN holding_constituents h ON h.trader_code = p.trader_code
WHERE p.report_type = 'regional' AND p.trader_code IS NOT NULL AND p.trader_code <> ''
ORDER BY p.sort_order, h.weight DESC;
```

**高价值新闻(重要性 + 情绪筛选)**

```sql
SELECT i.published_at, e.category, e.region, e.title_zh, e.summary_zh, i.url
FROM news_enrichments e
JOIN news_items i ON i.id = e.news_item_id
WHERE e.importance_score >= 70 AND e.sentiment <> 'neutral'
ORDER BY e.importance_score DESC, i.published_at DESC
LIMIT 100;
```

---

## 4. 使用注意

1. **快照,非实时。** 数据截止 2026-08-07,行情最后一天为 2026-08-06。需要新数据要重新导出 dump 再转换。
2. **时间全部是文本。** SQLite 无原生日期类型,格式为 `YYYY-MM-DD` / `YYYY-MM-DD HH:MM:SS`(UTC),字符串比较即可正确排序。
3. **繁体中文。** 所有 `*_zh` 字段是繁体,若下游需要简体需自行转换。
4. **`published_at` 有 107 行为 NULL,另有少量异常久远的日期**(部分源会回带 2005 年的老文章)。做时间窗口过滤时建议加 `published_at IS NOT NULL`,必要时用 `fetched_at` 兜底。
5. **涨跌幅单位分两种**:普通标的是百分比数值(`1.35` = +1.35%),`category = 'yield'` 的美债标的是基点数。详见 §2.5。
6. **未导出的表:** `alembic_version`、`surveys`、`survey_options`、`survey_submissions`、`submission_options`(与本次需求无关)。
