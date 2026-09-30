# ADR-0036：Review 模块标题与内容间距可编辑

- 日期：2026-09-29
- 状态：已接受
- 取代部分：[ADR-0035](0035-paged-freeform-opening-presentation.md)
- 关联：[ADR-0017](0017-continuous-html-and-paged-documents.md)、[ADR-0033](0033-controlled-page-one-presentation.md)

## 背景

ADR-0035 将 opening 页模块的标题文字和标题样式整体锁定，以保护参考报告的品牌层级。但编辑者
还需要分别调整每个标题与其下方正文或表格之间的距离；正文的段前后距不能准确表达这个模块边界，
也无法覆盖 Historical Performance 标题与表格之间的距离。

## 决策

- Review 页所有具有输出标题的模块均开放标题后距：四个 Review 正文模块及 Historical
  Performance。历史脚注在输出中没有独立标题，继续使用既有的表格—脚注间距控制。
- 复用 `presentation.page_one.elements[].title_style.space_after_pt` 作为每个模块独立的
  标题—内容间距，范围为 0–72pt、步长为 0.1pt。旧文档和未设置的模块继续使用 4pt 默认值，
  不新增 schema 或数据库迁移。
- 标题文字、字体、字号、颜色、字重、斜体、下划线、行高、段前距和对齐仍是锁定的品牌属性；
  服务端只接受 `space_after_pt`，并把其他客户端标题样式覆盖为模板默认值。
- 编辑器的模块精细编辑栏提供该数值控件；规范预览、分页 HTML/PDF 和可编辑 DOCX 从同一字段
  渲染，包括合法的 0pt 值。

## 结果

编辑者可以逐模块压缩或放大标题到正文／表格的留白，同时不开放品牌标题排版的其他自由度。
该值仍受服务端范围校验和分页溢出检查约束，跨格式共享同一终稿文档值。
