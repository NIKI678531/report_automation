# ADR-0033：第一页采用受控流式版式模型

- 日期：2026-09-25
- 状态：已接受
- 取代部分：[ADR-0025](0025-content-driven-review-export-layout.md)

## 背景

`3033-v2` 只在 Review block 上保存 `x/y/w/h`。它能够表达十二列拓扑，却无法统一描述
Review、Historical Performance 与历史脚注的相对位置，也没有安全的逐段字号、行距和对齐合同。
直接开放 CSS 或绝对坐标会使 HTML、PDF 与 DOCX 产生不同结果，并增加内容越过页脚安全区的风险。

## 决策

- `3033-v3` 在 `ReportDocument.presentation.schema_version=1` 下保存第一页元素。Review 使用
  `review:<block_id>` 稳定 ID，另外固定 `historical_performance` 与 `footnote:historical`。
- 元素保存十二列中的 `row/row_span/x/w` 和半行单位的 `vertical_nudge_steps`。这些字段只表达
  顺序、并列关系和有限留白，不换算为物理高度；渲染仍按实际内容流动，元素不得重叠。
- Historical Performance 与脚注保持满宽。脚注另有有限的 `bottom_nudge_steps`，逐段样式只能
  使用版本化字号、行距和对齐角色。Review HTML 的 `p/li` 同样只接受白名单 data 属性；任意
  CSS、字体名和数值均被拒绝。Review 默认使用 10pt／1.2 行距；模块标题在首次 v2 迁移后固定，
  产品／基准标题不在 Review 中提供编辑入口，v3 客户端也不能通过 API 改写这些标题。
- DOCX 使用与 HTML 相同的精确字号乘行距，而非依赖 Word 的“多倍行距”解释；脚注上下微调通过
  字符基线位移表达，允许档位为 -3 至 4，避免移动固定页脚 Logo 和页码。
- 所有格式通过 `PageOnePresentationResolver` 读取同一规范模型。草稿预览与保存调用同一纯
  canonicalization seam；草稿预览不创建文档版本或审计事件。
- 未定稿 v2 文档读取时只在内存适配。第一次成功保存时同时写入 presentation、创建 v3 文档版本
  并把报告模板身份升级到 `3033-v3`；已定稿或归档文档保持原模板身份。
- v2 `x/y/w/h` 在兼容期继续同步保存。旧客户端只改这些字段、新客户端只改 presentation 时均可
  正确合并；两边同时提交矛盾值则拒绝。
- 渲染器必须测量第一页安全区。草稿可显示溢出提示，但终稿化和导出以
  `PAGE_ONE_LAYOUT_OVERFLOW` 阻断；检测同时覆盖页脚边界、左右安全区和内部横向滚动，且不自动
  缩字、裁切或增加正文页。非法 presentation 统一返回 `PAGE_ONE_PRESENTATION_INVALID`。

## 结果

编辑器可以用受控方向键和逐段排版调整第一页，同时三个输出格式共享确定性模型。接口不接受
任意 CSS 或 PPT 式绝对坐标，旧 v2 草稿无需批量改写，历史终稿也不会被静默升级。

## 修订（2026-09-28）

- Review 工作台的 **Live paged preview** 只展示规范输出的第一页（Month in Review），直接使用与
  正式输出相同的分页页面，而不是另建一套预览排版。预览保留 A4（210 mm × 297 mm）几何比例，
  仅对整页做等比缩放以适配可用窗口；预览窗可收起和重新展开。
- `vertical_nudge_steps` 接受有符号整数；`0` 是默认基线而不是上移下限，编辑器不得因为元素仍在
  默认值就禁用向上箭头，也不以控件的人为档位限制继续上移。网格拓扑本身重叠继续返回
  `PAGE_ONE_PRESENTATION_INVALID`；有符号微调造成的实际渲染重叠，以及页脚／左右安全区溢出，
  均在草稿预览中标示并以 `PAGE_ONE_LAYOUT_OVERFLOW` 阻断终稿化和导出。
- `historical_performance` 增加受控表格排版：字号仅可为 9／10／11 pt，行距仅可为
  1.0／1.2／1.4。控件只改变表格文字与两行之间的排版，不得允许编辑基金、基准或期间回报数值；
  HTML、PDF、DOCX 均通过 `PageOnePresentationResolver` 解析同一组设置。
- 本修订不需要数据库迁移。`presentation.schema_version` 继续为 `1`，新增字段为可选字段并由
  resolver 提供保持现有外观的默认值；缺少这些字段的既有 v3 草稿、只含 v2 布局的旧稿及历史
  已定稿／归档文档继续按原兼容路径读取，不做批量或静默改写。
