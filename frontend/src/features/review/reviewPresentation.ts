export const GRID_COLUMNS = 12;
export const MAX_REVIEW_PAGES = 96;
export const MIN_VERTICAL_NUDGE_STEPS = -200;
export const MAX_VERTICAL_NUDGE_STEPS = 200;
export const MIN_OFFSET_Y_PT = -720;
export const MAX_OFFSET_Y_PT = 720;
// Keep all eight v3 bottom-nudge positions distinct within v4's non-negative gap range.
export const LEGACY_FOOTNOTE_GAP_BASE_PT = 16;
export const LEGACY_FOOTNOTE_NUDGE_STEP_PT = 4;
export const LEGACY_VERTICAL_NUDGE_STEP_PT = 5;
export const TYPOGRAPHY_LIMITS = {
  fontSize: { min: 5, max: 36, step: 0.1 },
  lineHeight: { min: 0.8, max: 3, step: 0.05 },
  spacing: { min: 0, max: 72, step: 0.1 },
  indent: { min: 0, max: 6, step: 1 },
} as const;

export type ReviewTextAlign = "left" | "center" | "right" | "justify";

/** Retained as input compatibility aliases for v3 callers and fixtures. */
export type ReviewFontSizeRole = "review-10" | "review-11";
export type FootnoteFontSizeRole = "footnote-8" | "footnote-9" | "footnote-10";
export type HistoricalTableFontSizeRole = "history-9" | "history-10" | "history-11";
export type LineHeightRole = "1.0" | "1.2" | "1.4";

export interface ReviewBlock {
  block_id: string;
  type: "rich_text" | "key_drivers" | "areas_to_monitor" | "outlook";
  title: string;
  content: string;
  x: number;
  y: number;
  w: number;
  h: number;
  text_align: ReviewTextAlign;
}

export interface TextStyle {
  font_family: string;
  font_size_pt: number;
  color: string;
  bold: boolean;
  italic: boolean;
  underline: boolean;
  line_height: number;
  space_before_pt: number;
  space_after_pt: number;
  text_align: ReviewTextAlign;
  indent_level?: number;
}

export interface FootnoteParagraphStyle {
  paragraph_index: number;
  font_size_role?: FootnoteFontSizeRole;
  line_height_role?: LineHeightRole;
  text_align: ReviewTextAlign;
}

export interface PageOneElement {
  id: string;
  row: number;
  row_span: number;
  x: number;
  w: number;
  vertical_nudge_steps?: number;
  title_style?: TextStyle;
  body_style?: TextStyle;
  page?: number;
  offset_y_pt?: number;
  gap_pt?: number;
  header_style?: TextStyle;
  cell_padding_y_pt?: number;
  content_html?: string;
  // Read-only compatibility fields accepted from v3 documents.
  table_font_size_role?: HistoricalTableFontSizeRole;
  table_line_height_role?: LineHeightRole;
  bottom_nudge_steps?: number;
  paragraph_styles?: FootnoteParagraphStyle[];
}

export interface PageOnePresentation {
  schema_version: 2;
  page_one: {
    review_page_count: number;
    elements: PageOneElement[];
  };
}

export const REVIEW_TITLE_STYLE: TextStyle = {
  font_family: "Calibri",
  font_size_pt: 14.04,
  color: "#22327F",
  bold: true,
  italic: false,
  underline: false,
  line_height: 1.2,
  space_before_pt: 0,
  space_after_pt: 4,
  text_align: "left",
  indent_level: 0,
};

export const REVIEW_BODY_STYLE: TextStyle = {
  font_family: "Calibri",
  font_size_pt: 10,
  color: "#000000",
  bold: false,
  italic: false,
  underline: false,
  line_height: 1.2,
  space_before_pt: 0,
  space_after_pt: 0,
  text_align: "left",
};

export const HISTORY_HEADER_STYLE: TextStyle = {
  ...REVIEW_BODY_STYLE,
  font_size_pt: 11,
  color: "#FFFFFF",
  bold: true,
  text_align: "center",
};

export const HISTORY_BODY_STYLE: TextStyle = { ...REVIEW_BODY_STYLE, text_align: "center" };
export const HISTORY_TITLE_STYLE: TextStyle = {
  ...REVIEW_TITLE_STYLE,
  font_size_pt: 12,
  text_align: "center",
};
export const FOOTNOTE_BODY_STYLE: TextStyle = { ...REVIEW_BODY_STYLE, font_size_pt: 9 };

const ALIGNMENTS: ReviewTextAlign[] = ["left", "center", "right", "justify"];
const SAFE_FONT_FAMILY = /^[\p{L}\p{N}\s.,'_+()&\/-]+$/u;
const HEX_COLOR = /^#[0-9a-f]{6}$/i;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function integer(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isInteger(value) ? value : fallback;
}

function boundedInteger(value: unknown, fallback: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, integer(value, fallback)));
}

function boundedNumber(value: unknown, fallback: number, min: number, max: number): number {
  return typeof value === "number" && Number.isFinite(value) && value >= min && value <= max ? value : fallback;
}

function boolean(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

export function normalizeTextStyle(value: unknown, fallback: TextStyle): TextStyle {
  const source = isRecord(value) ? value : {};
  const fontFamily = typeof source.font_family === "string" && source.font_family.trim().length <= 100 && SAFE_FONT_FAMILY.test(source.font_family.trim())
    ? source.font_family.trim()
    : fallback.font_family;
  return {
    font_family: fontFamily,
    font_size_pt: boundedNumber(source.font_size_pt, fallback.font_size_pt, TYPOGRAPHY_LIMITS.fontSize.min, TYPOGRAPHY_LIMITS.fontSize.max),
    color: typeof source.color === "string" && HEX_COLOR.test(source.color) ? source.color.toUpperCase() : fallback.color,
    bold: boolean(source.bold, fallback.bold),
    italic: boolean(source.italic, fallback.italic),
    underline: boolean(source.underline, fallback.underline),
    line_height: boundedNumber(source.line_height, fallback.line_height, TYPOGRAPHY_LIMITS.lineHeight.min, TYPOGRAPHY_LIMITS.lineHeight.max),
    space_before_pt: boundedNumber(source.space_before_pt, fallback.space_before_pt, TYPOGRAPHY_LIMITS.spacing.min, TYPOGRAPHY_LIMITS.spacing.max),
    space_after_pt: boundedNumber(source.space_after_pt, fallback.space_after_pt, TYPOGRAPHY_LIMITS.spacing.min, TYPOGRAPHY_LIMITS.spacing.max),
    text_align: ALIGNMENTS.includes(source.text_align as ReviewTextAlign) ? source.text_align as ReviewTextAlign : fallback.text_align,
    indent_level: boundedInteger(
      source.indent_level,
      fallback.indent_level ?? 0,
      TYPOGRAPHY_LIMITS.indent.min,
      TYPOGRAPHY_LIMITS.indent.max,
    ),
  };
}

function normalizeLockedTitleStyle(value: unknown, fallback: TextStyle): TextStyle {
  const source = isRecord(value) ? value : {};
  return {
    ...fallback,
    space_after_pt: boundedNumber(
      source.space_after_pt,
      fallback.space_after_pt,
      TYPOGRAPHY_LIMITS.spacing.min,
      TYPOGRAPHY_LIMITS.spacing.max,
    ),
    indent_level: boundedInteger(
      source.indent_level,
      fallback.indent_level ?? 0,
      TYPOGRAPHY_LIMITS.indent.min,
      TYPOGRAPHY_LIMITS.indent.max,
    ),
  };
}

function escapeHtml(value: string): string {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

export function historicalFootnoteParagraphs(value: string): string[] {
  const paragraphs = value.split(/\r?\n\s*\r?\n/).filter((paragraph) => paragraph.trim());
  return paragraphs.length ? paragraphs : [""];
}

export function plainTextToRichHtml(value: string): string {
  return historicalFootnoteParagraphs(value)
    .map((paragraph) => `<p>${escapeHtml(paragraph).replace(/\r?\n/g, "<br>")}</p>`)
    .join("");
}

export function richHtmlToPlainText(value: string): string {
  if (!value) return "";
  const document = new DOMParser().parseFromString(value, "text/html");
  const blocks = [...document.body.querySelectorAll("p, li, h2, h3, blockquote")]
    .filter((node) => !node.querySelector("p, li, h2, h3, blockquote"))
    .map((node) => node.textContent?.trim() ?? "")
    .filter(Boolean);
  return blocks.length ? blocks.join("\n\n") : (document.body.textContent ?? "").trim();
}

function wrapInlineContentsWithFontSize(element: Element, size: string): void {
  if (element.tagName === "LI") {
    const nestedBlocks = [...element.children].filter((child) => ["P", "H2", "H3", "BLOCKQUOTE"].includes(child.tagName));
    if (nestedBlocks.length) {
      nestedBlocks.forEach((block) => wrapInlineContentsWithFontSize(block, size));
      return;
    }
  }
  const span = element.ownerDocument.createElement("span");
  span.setAttribute("data-font-size-pt", size);
  while (element.firstChild) span.append(element.firstChild);
  element.append(span);
}

function migrateLegacyRichText(value: string): string {
  const document = new DOMParser().parseFromString(value, "text/html");
  document.body.querySelectorAll<HTMLElement>("[data-font-size-role]").forEach((element) => {
    const role = element.getAttribute("data-font-size-role") ?? "";
    const match = role.match(/^(?:review|footnote)-(8|9|10|11)$/);
    element.removeAttribute("data-font-size-role");
    if (!match) return;
    if (element.tagName === "SPAN") element.setAttribute("data-font-size-pt", match[1]);
    else wrapInlineContentsWithFontSize(element, match[1]);
  });
  document.body.querySelectorAll<HTMLElement>("[data-line-height-role]").forEach((element) => {
    const role = element.getAttribute("data-line-height-role") ?? "";
    element.removeAttribute("data-line-height-role");
    if (/^(?:1\.0|1\.2|1\.4)$/.test(role)) element.setAttribute("data-line-height", role);
  });
  return document.body.innerHTML;
}

function listHtml(rows: Array<Record<string, unknown>>, languageMode = "EN"): string {
  if (!rows.length) return languageMode === "ZH_HANS" || languageMode === "ZH_HANT" ? "<p></p>" : "<p>No content yet.</p>";
  return `<ul>${rows.map((row) => `<li><strong>${escapeHtml(String(row.title ?? ""))}</strong><p>${escapeHtml(String(row.body ?? ""))}</p></li>`).join("")}</ul>`;
}

export function legacyReviewBlocks(review: Record<string, unknown>, reviewTitle = "Monthly summary", languageMode = "EN", normalizeTitles = true): ReviewBlock[] {
  const titles: Record<string, Record<string, string>> = {
    drivers: { EN: "Key Drivers", ZH_HANS: "主要驱动因素", ZH_HANT: "主要驅動因素" },
    monitor: { EN: "Key Areas to Monitor", ZH_HANS: "重点关注领域", ZH_HANT: "重點關注領域" },
    outlook: { EN: "Outlook", ZH_HANS: "展望", ZH_HANT: "展望" },
  };
  const stored = Array.isArray(review.blocks) ? review.blocks as ReviewBlock[] : [];
  if (stored.length) return stored.map((block) => ({
    ...block,
    title: normalizeTitles && block.block_id === "summary" && ["Monthly summary", "Monthly Review", "月度回顾", "月度回顧", review.title, review.display_title].includes(block.title)
      ? reviewTitle
      : normalizeTitles && Object.values(titles[block.block_id] ?? {}).includes(block.title) ? titles[block.block_id][languageMode] ?? block.title : block.title,
    content: migrateLegacyRichText(block.content),
    text_align: ALIGNMENTS.includes(block.text_align) ? block.text_align : "left",
  }));
  return [
    { block_id: "summary", type: "rich_text", title: reviewTitle, content: `<p>${escapeHtml(String(review.summary ?? ""))}</p>`, x: 0, y: 0, w: 12, h: 4, text_align: "left" },
    { block_id: "drivers", type: "key_drivers", title: languageMode === "ZH_HANS" ? "主要驱动因素" : languageMode === "ZH_HANT" ? "主要驅動因素" : "Key Drivers", content: listHtml(Array.isArray(review.drivers) ? review.drivers as Array<Record<string, unknown>> : [], languageMode), x: 0, y: 4, w: 6, h: 7, text_align: "left" },
    { block_id: "monitor", type: "areas_to_monitor", title: languageMode === "ZH_HANS" ? "重点关注领域" : languageMode === "ZH_HANT" ? "重點關注領域" : "Key Areas to Monitor", content: listHtml(Array.isArray(review.monitor) ? review.monitor as Array<Record<string, unknown>> : [], languageMode), x: 6, y: 4, w: 6, h: 5, text_align: "left" },
    { block_id: "outlook", type: "outlook", title: languageMode === "ZH_HANS" || languageMode === "ZH_HANT" ? "展望" : "Outlook", content: `<p>${escapeHtml(String(review.outlook ?? ""))}</p>`, x: 6, y: 9, w: 6, h: 4, text_align: "left" },
  ];
}

function legacyRoleSize(value: unknown, fallback: number): number {
  const match = typeof value === "string" ? value.match(/(?:review|history|footnote)-(\d+)/) : null;
  return match ? Number(match[1]) : fallback;
}

function legacyRoleLineHeight(value: unknown, fallback: number): number {
  const parsed = typeof value === "string" ? Number(value) : Number.NaN;
  return Number.isFinite(parsed) ? parsed : fallback;
}

function legacyFootnoteRichHtml(value: string, valueStyles: unknown): string {
  const styles = new Map<number, Record<string, unknown>>();
  if (Array.isArray(valueStyles)) {
    valueStyles.filter(isRecord).forEach((style) => {
      if (typeof style.paragraph_index === "number" && Number.isInteger(style.paragraph_index)) {
        styles.set(style.paragraph_index, style);
      }
    });
  }
  const fontSizes: Record<string, number> = {
    "footnote-8": 8,
    "footnote-9": 9,
    "footnote-10": 10,
  };
  const lineHeights: Record<string, number> = { "1.0": 1, "1.2": 1.2, "1.4": 1.4 };
  return historicalFootnoteParagraphs(value).map((paragraph, index) => {
    const style = styles.get(index) ?? {};
    const fontSize = fontSizes[String(style.font_size_role ?? "")] ?? 8;
    const lineHeight = lineHeights[String(style.line_height_role ?? "")] ?? 1.2;
    const textAlign = ALIGNMENTS.includes(style.text_align as ReviewTextAlign)
      ? style.text_align as ReviewTextAlign
      : "left";
    const text = escapeHtml(paragraph).replace(/\r?\n/g, "<br>");
    return `<p data-line-height="${lineHeight}" data-text-align="${textAlign}"><span data-font-size-pt="${fontSize}">${text}</span></p>`;
  }).join("");
}

function legacyFootnoteGapPt(value: unknown): number {
  const steps = boundedInteger(value, 0, -3, 4);
  return LEGACY_FOOTNOTE_GAP_BASE_PT - steps * LEGACY_FOOTNOTE_NUDGE_STEP_PT;
}

export function pageOnePresentation(value: unknown, blocks: ReviewBlock[], historicalFootnote = ""): PageOnePresentation {
  const lastReviewRow = Math.max(0, ...blocks.map((block) => block.y + block.h));
  const defaults: PageOneElement[] = [
    ...blocks.map((block) => ({
      id: `review:${block.block_id}`,
      row: block.y,
      row_span: block.h,
      x: block.x,
      w: block.w,
      vertical_nudge_steps: 0,
      title_style: { ...REVIEW_TITLE_STYLE },
      body_style: { ...REVIEW_BODY_STYLE, text_align: block.text_align },
    })),
    {
      id: "historical_performance",
      row: lastReviewRow,
      row_span: 3,
      x: 0,
      w: GRID_COLUMNS,
      page: 1,
      offset_y_pt: 0,
      title_style: { ...HISTORY_TITLE_STYLE },
      header_style: { ...HISTORY_HEADER_STYLE },
      body_style: { ...HISTORY_BODY_STYLE },
      cell_padding_y_pt: 2,
    },
    {
      id: "footnote:historical",
      row: lastReviewRow + 3,
      row_span: 4,
      x: 0,
      w: GRID_COLUMNS,
      page: 1,
      gap_pt: 6,
      content_html: plainTextToRichHtml(historicalFootnote),
      body_style: { ...FOOTNOTE_BODY_STYLE },
    },
  ];
  const source = isRecord(value) && isRecord(value.page_one) && Array.isArray(value.page_one.elements) ? value : null;
  if (!source) return { schema_version: 2, page_one: { review_page_count: 1, elements: defaults } };

  const pageOne = source.page_one as Record<string, unknown>;
  const stored = new Map<string, Record<string, unknown>>(
    (pageOne.elements as unknown[]).filter(isRecord).map((element): [string, Record<string, unknown>] => [String(element.id ?? ""), element]),
  );
  const isV4 = source.schema_version === 2;
  const hasStoredReviewGeometry = [...stored.keys()].some((id) => id.startsWith("review:"));
  const storedHistory = stored.get("historical_performance");
  const storedFootnote = stored.get("footnote:historical");
  const requestedPage = boundedInteger(storedHistory?.page ?? storedFootnote?.page, 1, 1, MAX_REVIEW_PAGES);
  const requestedPageCount = boundedInteger(pageOne.review_page_count, requestedPage, requestedPage, MAX_REVIEW_PAGES);
  const elements = defaults.map((fallback) => {
    const element = stored.get(fallback.id);
    if (!element) return fallback;
    const useStoredGeometry = hasStoredReviewGeometry || fallback.id.startsWith("review:");
    if (fallback.id.startsWith("review:")) {
      return {
        ...fallback,
        row: useStoredGeometry ? boundedInteger(element.row, fallback.row, 0, 200) : fallback.row,
        row_span: useStoredGeometry ? boundedInteger(element.row_span, fallback.row_span, 1, 40) : fallback.row_span,
        x: useStoredGeometry ? boundedInteger(element.x, fallback.x, 0, GRID_COLUMNS - 1) : fallback.x,
        w: useStoredGeometry ? boundedInteger(element.w, fallback.w, 1, GRID_COLUMNS) : fallback.w,
        vertical_nudge_steps: boundedInteger(element.vertical_nudge_steps, 0, MIN_VERTICAL_NUDGE_STEPS, MAX_VERTICAL_NUDGE_STEPS),
        title_style: normalizeLockedTitleStyle(element.title_style, REVIEW_TITLE_STYLE),
        body_style: normalizeTextStyle(element.body_style, { ...REVIEW_BODY_STYLE, text_align: blocks.find((block) => `review:${block.block_id}` === fallback.id)?.text_align ?? "left" }),
      };
    }
    if (fallback.id === "historical_performance") {
      const legacyFontSize = legacyRoleSize(element.table_font_size_role, HISTORY_BODY_STYLE.font_size_pt);
      const legacyLineHeight = legacyRoleLineHeight(element.table_line_height_role, HISTORY_BODY_STYLE.line_height);
      return {
        ...fallback,
        row: isV4 ? boundedInteger(element.row, fallback.row, 0, 200) : fallback.row,
        row_span: isV4 ? boundedInteger(element.row_span, fallback.row_span, 1, 40) : fallback.row_span,
        x: isV4 ? boundedInteger(element.x, fallback.x, 0, GRID_COLUMNS - 1) : fallback.x,
        w: isV4 ? boundedInteger(element.w, fallback.w, 1, GRID_COLUMNS) : fallback.w,
        page: requestedPage,
        offset_y_pt: isV4
          ? boundedNumber(element.offset_y_pt, 0, MIN_OFFSET_Y_PT, MAX_OFFSET_Y_PT)
          : boundedInteger(
            element.vertical_nudge_steps,
            0,
            MIN_VERTICAL_NUDGE_STEPS,
            MAX_VERTICAL_NUDGE_STEPS,
          ) * LEGACY_VERTICAL_NUDGE_STEP_PT,
        title_style: normalizeLockedTitleStyle(element.title_style, HISTORY_TITLE_STYLE),
        header_style: normalizeTextStyle(element.header_style, { ...HISTORY_HEADER_STYLE, font_size_pt: legacyFontSize, line_height: legacyLineHeight }),
        body_style: normalizeTextStyle(element.body_style, { ...HISTORY_BODY_STYLE, font_size_pt: legacyFontSize, line_height: legacyLineHeight }),
        cell_padding_y_pt: boundedNumber(element.cell_padding_y_pt, 2, TYPOGRAPHY_LIMITS.spacing.min, TYPOGRAPHY_LIMITS.spacing.max),
      };
    }
    const footnoteHtml = !isV4
      ? legacyFootnoteRichHtml(historicalFootnote, element.paragraph_styles)
      : typeof element.content_html === "string" && element.content_html.trim()
        ? migrateLegacyRichText(element.content_html)
        : plainTextToRichHtml(historicalFootnote);
    return {
      ...fallback,
      row: isV4 ? boundedInteger(element.row, fallback.row, 0, 200) : fallback.row,
      row_span: isV4 ? boundedInteger(element.row_span, fallback.row_span, 1, 40) : fallback.row_span,
      x: isV4 ? boundedInteger(storedHistory?.x ?? element.x, fallback.x, 0, GRID_COLUMNS - 1) : fallback.x,
      w: isV4 ? boundedInteger(storedHistory?.w ?? element.w, fallback.w, 1, GRID_COLUMNS) : fallback.w,
      page: requestedPage,
      gap_pt: isV4
        ? boundedNumber(element.gap_pt, 6, TYPOGRAPHY_LIMITS.spacing.min, TYPOGRAPHY_LIMITS.spacing.max)
        : legacyFootnoteGapPt(element.bottom_nudge_steps),
      content_html: footnoteHtml,
      body_style: normalizeTextStyle(element.body_style, FOOTNOTE_BODY_STYLE),
    };
  });

  const history = elements.find((element) => element.id === "historical_performance");
  return {
    schema_version: 2,
    page_one: {
      review_page_count: requestedPageCount,
      elements: elements.map((element) => element.id === "footnote:historical" && history ? { ...element, page: history.page, x: history.x, w: history.w } : element),
    },
  };
}

export function retargetHistoricalFootnoteStyles(presentation: PageOnePresentation, footnote: string): PageOnePresentation {
  return {
    ...presentation,
    page_one: {
      ...presentation.page_one,
      elements: presentation.page_one.elements.map((element) => element.id === "footnote:historical"
        ? { ...element, content_html: plainTextToRichHtml(footnote) }
        : element),
    },
  };
}

export function updateElement(
  presentation: PageOnePresentation,
  id: string,
  update: (element: PageOneElement) => PageOneElement,
): PageOnePresentation {
  return {
    ...presentation,
    page_one: {
      ...presentation.page_one,
      elements: presentation.page_one.elements.map((element) => element.id === id ? update(element) : element),
    },
  };
}

export function updateHistoricalGroup(
  presentation: PageOnePresentation,
  update: (element: PageOneElement) => PageOneElement,
): PageOnePresentation {
  return {
    ...presentation,
    page_one: {
      ...presentation.page_one,
      elements: presentation.page_one.elements.map((element) => (
        element.id === "historical_performance" || element.id === "footnote:historical" ? update(element) : element
      )),
    },
  };
}
