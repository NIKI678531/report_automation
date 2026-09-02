---
version: alpha
description: >-
  CSOP 统一前端视觉语言 —— Gemini / Material You 风格的专业金融 UI：
  玻璃表面、弱阴影、渐变点缀、高信息密度；一屏一焦点、留白优先、动效传递因果。
colors:
  # ===== 主色与中性 =====
  primary: "#2361AD"
  primary-hover: "#1A4E8A"
  primary-container: "#E7EEF8"
  on-primary: "#FFFFFF"
  accent: "#60A5FA"
  # ===== 表面 & 背景 =====
  background: "#F8FAFC"
  background-overlay: "#F8FAFCCC"   # 80% alpha
  surface: "#FFFFFFCC"              # 80% alpha 玻璃
  surface-strong: "#FFFFFFEB"       # 92% alpha 弹层
  # ===== 文本 =====
  text: "#1E293B"
  text-secondary: "#64748B"
  text-disabled: "#94A3B8"
  # ===== 边框 =====
  border: "#64748B59"               # 35% alpha
  border-strong: "#64748B8C"
  # ===== 语义色 =====
  success: "#52C41A"
  warning: "#FAAD14"
  error: "#F5222D"
  info: "#1890FF"
  on-success: "#FFFFFF"
  on-warning: "#1E293B"
  on-error: "#FFFFFF"
  # ===== 分类语义色（用于 badge / chip） =====
  cat-research: "#2361AD"
  cat-marketing: "#722ED1"
  cat-trading: "#52C41A"
  cat-pcs: "#FAAD14"
  cat-data: "#1890FF"
  cat-system: "#6B7280"
  # ===== 暗色模式（对应 body.dark-mode 下的覆盖） =====
  dark-background: "#0F172A"
  dark-background-overlay: "#0F172AD1"
  dark-surface: "#1E293BB8"
  dark-text: "#E5E7EB"
  dark-text-secondary: "#C4C7C5"
  dark-border: "#94A3B847"

typography:
  # ===== 展示级 =====
  display-hero:
    fontFamily: Inter
    fontSize: 2.25rem      # 36px — Hero 主问题
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  # ===== 标题 =====
  h1:
    fontFamily: Inter
    fontSize: 1.5rem       # 24px — 页面区块标题
    fontWeight: 700
    lineHeight: 1.3
  h2:
    fontFamily: Inter
    fontSize: 1.25rem      # 20px
    fontWeight: 600
    lineHeight: 1.35
  h3:
    fontFamily: Inter
    fontSize: 1.125rem     # 18px — 卡片标题
    fontWeight: 600
    lineHeight: 1.4
  # ===== 正文 =====
  body-lg:
    fontFamily: Inter
    fontSize: 0.9375rem    # 15px — 输入框、强调正文
    fontWeight: 400
    lineHeight: 1.6
  body-md:
    fontFamily: Inter
    fontSize: 0.875rem     # 14px — 默认正文 / 描述
    fontWeight: 400
    lineHeight: 1.6
  body-sm:
    fontFamily: Inter
    fontSize: 0.8125rem    # 13px — 辅助说明
    fontWeight: 400
    lineHeight: 1.5
  # ===== 标签 & 徽章 =====
  label-md:
    fontFamily: Inter
    fontSize: 0.875rem     # 14px — chip / badge
    fontWeight: 500
    lineHeight: 1.2
  label-sm:
    fontFamily: Inter
    fontSize: 0.75rem      # 12px — lock / timestamp
    fontWeight: 500
    lineHeight: 1.2
  # ===== 数字（表格、KPI）=====
  numeric:
    fontFamily: "Roboto Mono"
    fontSize: 0.875rem
    fontWeight: 500
    lineHeight: 1.4
    fontFeature: "'tnum' on, 'lnum' on"

rounded:
  none: 0
  sm: 8px      # 按钮内部元素
  md: 10px     # 按钮
  lg: 12px     # 输入框
  xl: 16px     # 卡片 / 弹层
  pill: 9999px # chip / badge

spacing:
  none: 0
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  xxl: 40px
  page-x: 40px
  page-y: 32px
  grid-gap: 24px

components:
  # ===== 主按钮 =====
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.label-md}"
    rounded: "{rounded.md}"
    padding: 10px 18px
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-primary-disabled:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"

  # ===== 次级按钮（玻璃表面）=====
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.label-md}"
    rounded: "{rounded.md}"
    padding: 10px 18px
  button-secondary-hover:
    backgroundColor: "{colors.primary-container}"
    textColor: "{colors.primary}"

  # ===== Hero 发送圆钮 =====
  button-send:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.pill}"
    size: 36px
  button-send-hover:
    backgroundColor: "{colors.primary-hover}"

  # ===== 滚动提示胶囊按钮 =====
  button-scroll:
    backgroundColor: transparent
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.pill}"
    padding: 8px 16px
  button-scroll-hover:
    textColor: "{colors.primary}"

  # ===== 输入框 =====
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.body-lg}"
    rounded: "{rounded.lg}"
    padding: 12px 16px
    height: 48px
  input-focus:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"

  # ===== 卡片 =====
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.xl}"
    padding: 20px
  card-hover:
    backgroundColor: "{colors.surface}"
  card-disabled:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-disabled}"

  # ===== Badge / Chip（分类语义） =====
  badge-research:
    backgroundColor: "#2361AD3D"        # 24% alpha
    textColor: "{colors.cat-research}"
    typography: "{typography.label-md}"
    rounded: "{rounded.pill}"
    padding: 8px 14px
  badge-marketing:
    backgroundColor: "#722ED13D"
    textColor: "{colors.cat-marketing}"
    typography: "{typography.label-md}"
    rounded: "{rounded.pill}"
    padding: 8px 14px
  badge-trading:
    backgroundColor: "#52C41A3D"
    textColor: "{colors.cat-trading}"
    typography: "{typography.label-md}"
    rounded: "{rounded.pill}"
    padding: 8px 14px
  badge-pcs:
    backgroundColor: "#FAAD143D"
    textColor: "{colors.cat-pcs}"
    typography: "{typography.label-md}"
    rounded: "{rounded.pill}"
    padding: 8px 14px
  badge-data:
    backgroundColor: "#1890FF3D"
    textColor: "{colors.cat-data}"
    typography: "{typography.label-md}"
    rounded: "{rounded.pill}"
    padding: 8px 14px
  badge-system:
    backgroundColor: "#6B72802E"
    textColor: "#374151"
    typography: "{typography.label-md}"
    rounded: "{rounded.pill}"
    padding: 8px 14px

  # ===== 弹层 / 下拉 =====
  popover:
    backgroundColor: "{colors.surface-strong}"
    textColor: "{colors.text}"
    rounded: "{rounded.xl}"
    padding: 8px

  # ===== Toast =====
  toast-success:
    backgroundColor: "{colors.surface-strong}"
    textColor: "{colors.text}"
    rounded: "{rounded.lg}"
    padding: 12px 16px
  toast-error:
    backgroundColor: "{colors.surface-strong}"
    textColor: "{colors.error}"
    rounded: "{rounded.lg}"
    padding: 12px 16px
---

## Overview

**Architectural Minimalism meets Financial Gravitas.** 本设计系统面向 CSOP
投资研究、交易、营销与运营平台，定位为 **"Gemini / Material You 式的专业金融 UI"**：
玻璃表面、弱阴影、渐变点缀、高信息密度、高可读性。

设计目标是 **"Less, but more modern"** —— UI 简洁但每一处都显得考究，
信息密度高而不拥挤，交互轻但反馈丰富。评审与实现时以下八条原则逐条核对：

1. **一屏一焦点 (One Hero per Screen)** — 每个页面只能有一个 L1 主角（Hero
   输入、主 CTA 或主图表），用尺寸 / 饱和度 / 动效三重强调；其余降维。
2. **留白优先 (Whitespace over borders)** — 用 `spacing` 和层级而非 `border`
   分组；默认 border 透明，仅在 `:focus` / `:hover` 显现。
3. **玻璃 + 弱阴影 (Soft Glass, never Hard Box)** — 卡片与弹层统一
   `{colors.surface}` + `backdrop-filter: blur(8~16px)` + 柔和阴影。
   **禁用** "纯白 + 硬描边" 组合。
4. **渐变点缀 (Gradient Accents, not Fills)** — 大面积使用 neutral；仅
   在主按钮、激活 chip、标题 underline 等 **强调点** 使用品牌渐变。
5. **动效传递因果 (Motion = Causality)** — 所有 UI 状态变化必须有过渡，
   **禁止** 状态突变。
6. **微交互即反馈 (Micro-interactions Everywhere)** — `default / hover /
   active / disabled` 四态齐全；按钮点击 `scale(0.97)`；输入框聚焦有 glow ring。
7. **首屏叙事 (Greeting, not Dashboard)** — 首屏为 "问候 + 一句话 + 一个主输入
   + 少量入口 chip"；复杂信息向下折叠。
8. **可读性绝不妥协 (Readability First)** — 正文 ≥ 14px、行高 1.6；
   金额/数字 `tabular-nums`；对比度 ≥ WCAG AA（4.5:1）。

## Colors

色板以 **高对比中性 + 单一主色 + 六类分类语义色** 为核心，避免大面积饱和色块。

- **Primary `{colors.primary}` (#2361AD)** — CSOP 品牌蓝，主 CTA、激活态、
  选中强调的唯一驱动色。避免作为大面积背景。
- **Primary Hover `{colors.primary-hover}`** — hover 下沉，与 Primary 形成
  清晰的因果反馈。
- **Accent `{colors.accent}` (#60A5FA)** — 仅用于链接、焦点环（带透明度）与
  渐变终点。
- **Background `{colors.background}` / Surface `{colors.surface}`** — 页面底色
  是接近纯白的 slate `#F8FAFC`；卡片与弹层使用 80% 不透明白色玻璃，叠加
  `backdrop-filter: blur()` 形成层次。
- **Text 体系** — `text` 用于正文，`text-secondary` 用于描述/时间戳/
  placeholder，`text-disabled` 用于禁用态。
- **Border `{colors.border}`** — 默认 35% 灰度透明，仅在聚焦/悬停时提升为
  `primary`，避免硬线切割界面。
- **Semantic（success / warning / error / info）** — 仅用于状态图标、左侧色条
  或小面积强调，**不使用** 整条背景色。
- **Category（research / marketing / trading / pcs / data / system）** — 仅
  通过 `badge-*` 组件出现，承载业务分类语义，严禁在非分类上下文中借用。

**暗色模式**：仅覆写 `dark-*` 前缀 tokens，不改组件结构。深色下的文本对比度
必须复核 ≥ WCAG AA。

## Typography

- **字体族**：`Inter, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif`；
  数字场景（KPI、金额、表格）切到 `Roboto Mono` 并开启 `tnum / lnum`。
- **字号阶梯**：
  - `display-hero` 36px —— 仅用于每页 Hero 区的主问题（一屏一焦点）。
  - `h1 / h2 / h3` 24 / 20 / 18px —— 区块标题与卡片标题。
  - `body-lg / body-md / body-sm` 15 / 14 / 13px —— 正文三档，默认 14px。
  - `label-md / label-sm` 14 / 12px —— chip、badge、lock hint。
  - `numeric` —— 所有金额、百分比、表格数字必须走此 token，保证列对齐。
- **行高**：正文恒为 `1.6`，标题 `1.25–1.4`；**禁止** 使用 1.0 以下紧排（损失
  可读性）。
- **字重**：正文 `400`，强调 `500`，标题 `600–700`；不使用 300 以下，避免在
  金融场景中过度轻盈。

## Layout

所有 "首页 / 工作台类" 页面采用三段式骨架：
**液态背景层（z:0，`pointer-events:none`）+ Hero 区 + 内容 / 功能区**。

- **页面外层**：`spacing.page-y spacing.page-x`（32 40），`min-height: 100vh`。
- **内容最大宽**：1440px；Hero 输入最大 720px 居中。
- **网格**：`grid-template-columns: repeat(auto-fit, minmax(300px, 1fr))`，
  `gap: spacing.grid-gap (24px)`。
- **响应式断点**：`768 / 1024 / 1440`。
- **背景遮罩**：在动态背景（WebGL / Canvas）上必须叠加
  `{colors.background-overlay}` 半透明层以保障可读性。
- **z-index 层级**：`bg: 0`，`content: 2`，`dropdown: 1000`，`modal: 2000`，
  `message: 3000`。

## Elevation & Depth

本系统不使用多级硬阴影，而用 **"玻璃 + 弱阴影 + 边缘高光"** 三件套表达层次：

- **Level 0（页面底层）** — 无阴影，仅颜色。
- **Level 1（卡片 / 输入框）** — `0 2px 6px rgba(35,97,173,0.18)`（主按钮）
  或无阴影（卡片默认）；依赖 surface 透明度与 `backdrop-filter: blur(8px)`
  区分。
- **Level 2（hover 卡片 / 弹层）** — `0 8px 24px rgba(17,24,39,0.08~0.10)`；
  `blur(16px)`。
- **Level 3（模态 / 置顶通知）** — `0 12px 32px rgba(17,24,39,0.10)` +
  边缘高光 `linear-gradient(135deg, rgba(255,255,255,0.5), transparent 60%)`。
- **Focus Ring** — 采用 4px 柔光圈 `box-shadow: 0 0 0 4px rgba(35,97,173,0.14)`，
  不使用硬描边作为聚焦指示。

## Shapes

- 按钮及内部控件使用 `rounded.md` (10px)；输入框 `rounded.lg` (12px)；
  卡片与弹层 `rounded.xl` (16px)；chip 与 badge 使用 `rounded.pill` (9999px)。
- **禁止** 在同一个组件族内混用多个 radius（例如同一张卡片内的按钮必须全部
  使用 `rounded.md`）。
- 圆形元素仅用于头像和 Hero 发送按钮（`button-send`，36×36 pill）。
- 角色高光 / 激活态通过 **顶部 2–3px 渐变描边** 表达，而非整框描边。

## Components

组件 tokens 详见 front matter。以下为应用约定与 **变体命名规则**：

- 变体（hover / active / pressed / disabled）统一用 **独立组件条目**
  `{name}-{state}` 表示（如 `button-primary-hover`），不以嵌套状态表达。
- **四态齐全是硬要求**：任何可点击元素必须同时定义
  `default / hover / active / disabled` 外加 `focus-visible` 的 glow ring。
- `button-primary` 在强调场景可应用渐变：
  `linear-gradient(135deg, #2361AD 0%, #4A8ED6 100%)`。
- `card` 的 hover 动效：`translateY(-4px)` + Level 2 阴影 + 边缘高光浮层渐显。
- `badge-*` 仅作分类语义，**不用于** 表示状态（状态用图标 + 语义色）。
- `input` 聚焦：`border` 变 `primary` + glow ring，**不使用** 底部下划线。
- `popover` 必须配合进入动效 `pop-in`
  （`opacity 0 → 1`、`translateY(-6px) scale(0.98) → 0 / 1`，时长 200ms，
  emphasized 曲线）。
- `toast` 进入：`translateX(24px) + opacity 0 → 0 + 1`；左侧色条宽 3px；
  **不使用** 整条语义背景色。
- 列表与卡片网格入场统一使用 **瀑布 stagger**：`animationDelay: i * 60ms`，
  上限 600ms。

**动效时长与曲线**（统一词汇表，不自造新值）：

| 名称 | 值 | 用途 |
|:--|:--|:--|
| `dur-micro` | 120ms | hover、按钮回弹 |
| `dur-fast` | 200ms | tooltip、badge、popover |
| `dur-base` | 300ms | 面板展开、cross-fade |
| `dur-slow` | 500ms | 页面切换、Hero 变形 |
| `dur-scroll` | 800ms | 长距离平滑滚动 |
| `ease-standard` | `cubic-bezier(0.4, 0, 0.2, 1)` | 默认 |
| `ease-emphasized` | `cubic-bezier(0.2, 0, 0, 1)` | 入场 / 强调 |
| `ease-bounce` | `cubic-bezier(0.34, 1.56, 0.64, 1)` | 拖拽落下回弹 |

## Do's and Don'ts

**Do**
- ✅ 使用 tokens 引用（`{colors.primary}` / `{rounded.xl}` / `{spacing.md}`），
  **永远不** 在组件中硬编码色值、圆角、间距。
- ✅ 大面积使用 neutral（`background` / `surface`），仅在强调点叠加品牌渐变。
- ✅ 卡片与弹层坚持 "玻璃 + `backdrop-filter` + 弱阴影"。
- ✅ 列表加载使用 skeleton + shimmer，暗示即将出现的版式。
- ✅ 所有动效必须包含 `@media (prefers-reduced-motion: reduce)` 降级。
- ✅ 金额 / 百分比 / 表格数字一律使用 `{typography.numeric}`（`tnum`）。
- ✅ 可点击元素同时提供 `default / hover / active / disabled / focus-visible`
  五个状态；按下用 `scale(0.97)` 传递因果。
- ✅ i18n：所有用户可见文案经 `t(key, '中文 fallback')`，zh / en / ko / zh-TW
  四语种齐备。

**Don't**
- ❌ 禁止 "纯白卡片 + 硬描边" 组合；禁止大面积饱和色块做背景。
- ❌ 禁止使用 spinner 作为列表级加载（改用 skeleton）。
- ❌ 禁止状态突变（无过渡的显隐、位移、折叠）。
- ❌ 禁止把分类 `badge-*` 借用为状态指示；状态用图标 + 语义色。
- ❌ 禁止自造动效时长 / 曲线；必须引用 `dur-* / ease-*` 词汇表。
- ❌ 禁止只写 `:hover` 而缺 `:active` / `:disabled` / `:focus-visible`。
- ❌ 禁止循环打字机、闪烁光标等在金融专业场景中显得"花哨"的动效。
- ❌ 禁止用 `!important` / 内联 style 覆盖 Ant Design；应改主题 token 或
  `ConfigProvider`。
- ❌ 禁止在非强调点使用品牌渐变（例如整张卡片背景）。
