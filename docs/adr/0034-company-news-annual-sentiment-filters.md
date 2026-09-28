# ADR-0034：Company News 年度窗口与情绪筛选

- 日期：2026-09-25
- 状态：已接受
- 关联：[ADR-0002](0002-da-report-company-news-catalog.md)、[ADR-0022](0022-company-news-constituent-scope.md)

## 背景

Company News 原先默认展示 DA-Report 的完整历史区间，并提供动态情绪和重要度下拉筛选。
全历史 facet 的项目与计数会随上游数据变化，编辑者也需要先手动收窄到报告相关年度，
因此默认结果与月报工作上下文不够稳定。

## 决策

- 前端从 `report_date` 的字符串年份直接构造 `YYYY-01-01` 至 `YYYY-12-31`，并在首次请求、
  搜索、排序和游标翻页时始终发送该日期范围。日期输入框直接绑定当前筛选状态，不使用
  全历史 facet 的最早或最晚日期作为显示回退。
- 情绪筛选固定为 `All / Bullish / Neutral / Bearish`，对应未传参数、`bull`、`neutral`、
  `bear`。简体和繁体中文均显示“全部 / 看多 / 中性 / 看空”。未知情绪只在 All 结果中出现。
- 筛选器不显示 facet 计数。Company News 页面移除 Importance 筛选及其请求参数；新闻卡片仍可
  展示已有重要度元数据，后端 `importance` 查询参数、facet、评分和审计合同继续保留，供既有
  API 客户端使用。
- “清除筛选”恢复年度日期基线、All companies、All sentiment 和默认排序；年度基线本身不视为
  活跃筛选。首屏和翻页复用同一个查询参数构造函数，避免游标请求丢失筛选上下文。

## 结果

编辑者打开模块即可看到报告年度内的新闻，并能用稳定、无计数的四段情绪控件筛选。
本次不修改后端或数据库契约；需要浏览年度之外数据时仍可手动调整日期输入框，现有 API 客户端
也可继续使用 Importance 筛选。
