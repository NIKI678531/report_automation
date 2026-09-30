# ADR-0035：首页受控自由排版与手工续页

- 日期：2026-09-29
- 状态：已接受
- 取代部分：[ADR-0033](0033-controlled-page-one-presentation.md)
- 关联：[ADR-0014](0014-advisory-release-checks-and-direct-downloads.md)、[ADR-0017](0017-continuous-html-and-paged-documents.md)、[ADR-0032](0032-fixed-fifth-page-compliance-disclaimer.md)

## 背景

`3033-v3` 只允许预设字号、行距和有界微调，且把任何第一页越界视为定稿与导出的硬错误。
编辑者需要恢复模块拖拽手柄、精确编辑文字与表格排版，并允许 Historical Performance 与其历史
脚注作为一组手工下移到带完整页眉页脚的续页。内容自身变长不能悄悄改变页数；旧终稿也不能因
新的布局规则被重排。

## 决策

- `3033-v4` 使用 `presentation.schema_version=2`。四个 Review 模块仍在 opening 第 1 页，保存
  十二列拓扑、可调高度与正文样式。Historical Performance 和历史脚注组成同页、同宽、
  不可拆分的布局组；组可位于 opening 第 1 至 96 页，报告总页数因此最多为 100 页。
- 续页只由明确的移动操作创建。正文溢出只显示诊断，不自动分页。每个 opening 页重复正式页眉、
  Logo、页脚和连续页码；Company News、Constituents、Analytics 与免责声明顺次后移，免责声明仍
  是最后一页。连续 HTML 继续遵循 ADR-0017，不显示运行页眉页脚。
- 模块标题文字、标题样式和绑定表格数据保持不可改。标题使用批准参考 PDF 的品牌默认值：Review
  为左对齐的 Calibri Bold 14.04pt、`#22327F`，Historical Performance 为居中的 Calibri Bold
  12pt、同色；服务端
  会覆盖客户端对标题样式的修改。正文样式使用经类型校验的数值合同：字号范围 5–36pt，行距
  0.8–3，段前后距及表格上下内边距 0–72pt。Review 与脚注支持选区字体、字号、颜色、粗体、
  斜体、下划线，以及段落行距、间距和对齐；History 表头和数据行可分别设置。
- 所有受控富文本以及 06 Footnotes & Disclosures、新闻标题和摘要支持角标工具。用户可输入数字、
  既有 Unicode 上标或 `*†‡`，并把规范化后的 Unicode 角标插入当前选区之前或之后；因此 PDF、
  HTML、DOCX 与派生纯文本共享同一内容，不引入原始 CSS 或不安全 HTML。
- 字体名是受长度和字符集约束的数据而非原始 CSS。随镜像安装的 Carlito、Noto CJK 字体提供
  确定输出；Calibri 在 Chromium 中使用 Carlito 兼容替代。其他名称允许保存，但预览和导出明确
  记录回退告警，DOCX 保留请求的字体名。
- 布局测量输出结构化 finding。纯纵向超出正文安全边界不超过 3mm 且未触碰页眉、Logo、页码或
  页脚时降级为 `PAGE_LAYOUT_TOLERANCE_USED`，允许定稿和导出；更大越界、横向裁切、模块重叠或
  隐藏内容继续阻断。`QA_BLOCKED` 保留为数据质量状态，但依 ADR-0014 不作为定稿或下载门禁。
- 可编辑 v1–v3 草稿只在读取时适配，首次成功保存才创建 v4 文档版本并升级报告身份。既有
  FINALIZED／ARCHIVED 文档始终使用原模板和原页数渲染。

## 结果

首页编辑器获得可追踪、跨格式一致的自由排版和手工续页能力，同时仍由服务端限制可渲染范围、
隔离危险样式并保留历史终稿。自动放行仅覆盖量化的 3mm 纵向缓冲，不构成对安全、完整性、权限、
免责声明或内容裁切检查的豁免。
