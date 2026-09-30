# ADR-0037：Review 小标题编辑与两字符整块缩进

- 日期：2026-09-30
- 状态：已接受
- 取代部分：[ADR-0035](0035-paged-freeform-opening-presentation.md)、[ADR-0036](0036-editable-review-title-content-spacing.md)
- 关联：[ADR-0017](0017-continuous-html-and-paged-documents.md)

## 背景

Review 编辑者需要修改四个正文模块的小标题，并分别控制小标题与正文的整块左缩进。此前标题文字
保持锁定，且缩进只存在于富文本中的单个段落，无法表达模块标题与完整正文一起或分别缩进的排版。

## 决策

- 四个 Review 模块的 `blocks[].title` 开放编辑，仍执行非空及最多 200 字符校验；summary 模块标题
  继续同步 `month_in_review.title` 与 `display_title`。产品主标题、基准名称及其品牌字体样式仍锁定。
- `title_style` 与 `body_style` 新增 `indent_level`，范围为 0–6。每一级代表两个当前字号字符宽度
  （`2em`），标题和正文分别设置；0 表示不缩进。
- 富文本段落的 `data-indent-level` 使用同一 0–6 级合同。编号列表保留悬挂编号，换行后的正文与
  小标题正文起点对齐；模块级正文缩进与段落级缩进可以叠加。
- 规范 HTML、分页 PDF 和 DOCX 使用相同字段。HTML/PDF 使用 `em`，DOCX 按当前段落或标题字号
  换算为点值。不新增数据库列或迁移，旧文档缺省为 0。

## 结果

编辑者可在展开的 Review 模块中修改小标题，并分别为标题和完整正文设置两字符步进的整块缩进；
选中的单个段落或编号项仍可用工具栏独立缩进，且三个导出格式保持一致。
