import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { Extension } from "@tiptap/core";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { AlignCenter, AlignJustify, AlignLeft, AlignRight, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Bold, ChevronLeft, ChevronRight, Eye, Italic, Link2, List, Pencil } from "lucide-react";
import GridLayout, { WidthProvider, type Layout } from "react-grid-layout";
import { useLocale } from "../../i18n";

const TwelveColumnGrid = WidthProvider(GridLayout);
const GRID_COLUMNS = 12;
const MIN_VERTICAL_NUDGE_STEPS = -200;
const MAX_VERTICAL_NUDGE_STEPS = 200;
const MIN_FOOTNOTE_NUDGE_STEPS = -3;
const MAX_FOOTNOTE_NUDGE_STEPS = 4;

export type ReviewTextAlign = "left" | "center" | "right" | "justify";
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

export interface FootnoteParagraphStyle {
  paragraph_index: number;
  font_size_role: FootnoteFontSizeRole;
  line_height_role: LineHeightRole;
  text_align: ReviewTextAlign;
}

export interface PageOneElement {
  id: string;
  row: number;
  row_span: number;
  x: number;
  w: number;
  vertical_nudge_steps: number;
  table_font_size_role?: HistoricalTableFontSizeRole;
  table_line_height_role?: LineHeightRole;
  bottom_nudge_steps?: number;
  paragraph_styles?: FootnoteParagraphStyle[];
}

export interface PageOnePresentation {
  schema_version: 1;
  page_one: { elements: PageOneElement[] };
}

const FONT_SIZE_ROLES: ReviewFontSizeRole[] = ["review-10", "review-11"];
const FOOTNOTE_FONT_SIZE_ROLES: FootnoteFontSizeRole[] = ["footnote-8", "footnote-9", "footnote-10"];
const HISTORICAL_TABLE_FONT_SIZE_ROLES: HistoricalTableFontSizeRole[] = ["history-9", "history-10", "history-11"];
const LINE_HEIGHT_ROLES: LineHeightRole[] = ["1.0", "1.2", "1.4"];
const TEXT_ALIGNMENTS: Array<{ value: ReviewTextAlign; icon: typeof AlignLeft }> = [
  { value: "left", icon: AlignLeft },
  { value: "center", icon: AlignCenter },
  { value: "right", icon: AlignRight },
  { value: "justify", icon: AlignJustify },
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function integer(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isInteger(value) ? value : fallback;
}

function listHtml(rows: Array<Record<string, unknown>>, languageMode = "EN"): string {
  if (!rows.length) return languageMode === "ZH_HANS" || languageMode === "ZH_HANT" ? "<p></p>" : "<p>No content yet.</p>";
  return `<ul>${rows.map((row) => `<li><strong>${String(row.title ?? "")}</strong><p>${String(row.body ?? "")}</p></li>`).join("")}</ul>`;
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
    text_align: TEXT_ALIGNMENTS.some(({ value }) => value === block.text_align) ? block.text_align : "left",
  }));
  return [
    { block_id: "summary", type: "rich_text", title: reviewTitle, content: `<p>${String(review.summary ?? "")}</p>`, x: 0, y: 0, w: 12, h: 4, text_align: "left" },
    { block_id: "drivers", type: "key_drivers", title: languageMode === "ZH_HANS" ? "主要驱动因素" : languageMode === "ZH_HANT" ? "主要驅動因素" : "Key Drivers", content: listHtml(Array.isArray(review.drivers) ? review.drivers as Array<Record<string, unknown>> : [], languageMode), x: 0, y: 4, w: 6, h: 7, text_align: "left" },
    { block_id: "monitor", type: "areas_to_monitor", title: languageMode === "ZH_HANS" ? "重点关注领域" : languageMode === "ZH_HANT" ? "重點關注領域" : "Key Areas to Monitor", content: listHtml(Array.isArray(review.monitor) ? review.monitor as Array<Record<string, unknown>> : [], languageMode), x: 6, y: 4, w: 6, h: 5, text_align: "left" },
    { block_id: "outlook", type: "outlook", title: languageMode === "ZH_HANS" || languageMode === "ZH_HANT" ? "展望" : "Outlook", content: `<p>${String(review.outlook ?? "")}</p>`, x: 6, y: 9, w: 6, h: 4, text_align: "left" },
  ];
}

export function pageOnePresentation(value: unknown, blocks: ReviewBlock[]): PageOnePresentation {
  const lastReviewRow = Math.max(0, ...blocks.map((block) => block.y + block.h));
  const defaults: PageOneElement[] = [
    ...blocks.map((block) => ({ id: `review:${block.block_id}`, row: block.y, row_span: block.h, x: block.x, w: block.w, vertical_nudge_steps: 0 })),
    { id: "historical_performance", row: lastReviewRow, row_span: 1, x: 0, w: GRID_COLUMNS, vertical_nudge_steps: 0, table_font_size_role: "history-10", table_line_height_role: "1.2" },
    { id: "footnote:historical", row: lastReviewRow + 1, row_span: 1, x: 0, w: GRID_COLUMNS, vertical_nudge_steps: 0, bottom_nudge_steps: 0, paragraph_styles: [] },
  ];
  if (!isRecord(value) || value.schema_version !== 1 || !isRecord(value.page_one) || !Array.isArray(value.page_one.elements)) {
    return { schema_version: 1, page_one: { elements: defaults } };
  }
  const stored = new Map(value.page_one.elements.filter(isRecord).map((element) => [String(element.id ?? ""), element]));
  const hasStoredReviewGeometry = [...stored.keys()].some((id) => id.startsWith("review:"));
  const elements = defaults.map((fallback) => {
    const element = stored.get(fallback.id);
    if (!element) return fallback;
    const useStoredGeometry = hasStoredReviewGeometry || fallback.id.startsWith("review:");
    const paragraphStyles = Array.isArray(element.paragraph_styles)
      ? element.paragraph_styles.filter(isRecord).map((style, paragraphIndex) => ({
        paragraph_index: integer(style.paragraph_index, paragraphIndex),
        font_size_role: FOOTNOTE_FONT_SIZE_ROLES.includes(style.font_size_role as FootnoteFontSizeRole) ? style.font_size_role as FootnoteFontSizeRole : "footnote-8",
        line_height_role: LINE_HEIGHT_ROLES.includes(style.line_height_role as LineHeightRole) ? style.line_height_role as LineHeightRole : "1.2",
        text_align: TEXT_ALIGNMENTS.some(({ value: alignment }) => alignment === style.text_align) ? style.text_align as ReviewTextAlign : "left",
      })) : fallback.paragraph_styles;
    return {
      ...fallback,
      row: useStoredGeometry ? integer(element.row, fallback.row) : fallback.row,
      row_span: useStoredGeometry ? integer(element.row_span, fallback.row_span) : fallback.row_span,
      x: useStoredGeometry ? integer(element.x, fallback.x) : fallback.x,
      w: useStoredGeometry ? integer(element.w, fallback.w) : fallback.w,
      vertical_nudge_steps: integer(element.vertical_nudge_steps, fallback.vertical_nudge_steps),
      ...(fallback.id === "historical_performance" ? {
        table_font_size_role: HISTORICAL_TABLE_FONT_SIZE_ROLES.includes(element.table_font_size_role as HistoricalTableFontSizeRole) ? element.table_font_size_role as HistoricalTableFontSizeRole : "history-10",
        table_line_height_role: LINE_HEIGHT_ROLES.includes(element.table_line_height_role as LineHeightRole) ? element.table_line_height_role as LineHeightRole : "1.2",
      } : {}),
      ...(fallback.id === "footnote:historical" ? { bottom_nudge_steps: integer(element.bottom_nudge_steps, fallback.bottom_nudge_steps ?? 0), paragraph_styles: paragraphStyles ?? [] } : {}),
    };
  });
  return { schema_version: 1, page_one: { elements } };
}

export function historicalFootnoteParagraphs(value: string): string[] {
  const paragraphs = value.split(/\r?\n\s*\r?\n/).filter((paragraph) => paragraph.trim());
  return paragraphs.length ? paragraphs : [""];
}

export function retargetHistoricalFootnoteStyles(
  presentation: PageOnePresentation,
  footnote: string,
): PageOnePresentation {
  const paragraphCount = historicalFootnoteParagraphs(footnote).length;
  return {
    ...presentation,
    page_one: {
      ...presentation.page_one,
      elements: presentation.page_one.elements.map((element) => (
        element.id === "footnote:historical"
          ? {
            ...element,
            paragraph_styles: (element.paragraph_styles ?? []).filter(
              (style) => style.paragraph_index < paragraphCount,
            ),
          }
          : element
      )),
    },
  };
}

const ParagraphStyle = Extension.create({
  name: "paragraphStyle",
  addGlobalAttributes() {
    return [{
      types: ["paragraph", "listItem"],
      attributes: {
        fontSizeRole: { default: null, parseHTML: (element) => element.getAttribute("data-font-size-role"), renderHTML: (attributes) => attributes.fontSizeRole ? { "data-font-size-role": attributes.fontSizeRole } : {} },
        lineHeightRole: { default: null, parseHTML: (element) => element.getAttribute("data-line-height-role"), renderHTML: (attributes) => attributes.lineHeightRole ? { "data-line-height-role": attributes.lineHeightRole } : {} },
        textAlign: { default: null, parseHTML: (element) => element.getAttribute("data-text-align"), renderHTML: (attributes) => attributes.textAlign ? { "data-text-align": attributes.textAlign } : {} },
      },
    }];
  },
});

function RichTextBlock({ block, disabled, selected, onSelect, onChange }: { block: ReviewBlock; disabled: boolean; selected: boolean; onSelect: () => void; onChange: (content: string) => void }) {
  const { t } = useLocale();
  const [, setSelectionRevision] = useState(0);
  const editor = useEditor({
    extensions: [StarterKit.configure({ link: { openOnClick: false } }), ParagraphStyle],
    content: block.content,
    editable: !disabled,
    onSelectionUpdate: () => setSelectionRevision((revision) => revision + 1),
    onUpdate: ({ editor: activeEditor }) => onChange(activeEditor.getHTML()),
  });
  useEffect(() => { editor?.setEditable(!disabled); }, [disabled, editor]);
  useEffect(() => { if (editor && editor.getHTML() !== block.content) editor.commands.setContent(block.content); }, [block.content, editor]);
  const activeNode = editor?.isActive("listItem") ? "listItem" : "paragraph";
  const attributes = editor?.getAttributes(activeNode) ?? {};
  const fontSizeRole = FONT_SIZE_ROLES.includes(attributes.fontSizeRole as ReviewFontSizeRole) ? attributes.fontSizeRole as ReviewFontSizeRole : "review-10";
  const lineHeightRole = LINE_HEIGHT_ROLES.includes(attributes.lineHeightRole as LineHeightRole) ? attributes.lineHeightRole as LineHeightRole : "1.2";
  const textAlign = TEXT_ALIGNMENTS.some(({ value }) => value === attributes.textAlign) ? attributes.textAlign as ReviewTextAlign : block.text_align;
  const updateStyle = (attribute: "fontSizeRole" | "lineHeightRole" | "textAlign", value: string) => {
    if (!editor) return;
    editor.chain().focus().updateAttributes(activeNode, { [attribute]: value }).run();
  };
  const setAlignment = (alignment: ReviewTextAlign) => updateStyle("textAlign", alignment);
  return <article className={`review-block${selected ? " selected" : ""}`} data-layout-id={`review:${block.block_id}`} onClick={onSelect}>
    <header><strong>{block.title}</strong><span>{block.w}/12</span></header>
    <div className="rich-toolbar" aria-label={t("textFormatting")}>
      <button className="icon-button" title={t("bold")} disabled={disabled} onClick={() => editor?.chain().focus().toggleBold().run()}><Bold size={15} /></button>
      <button className="icon-button" title={t("italic")} disabled={disabled} onClick={() => editor?.chain().focus().toggleItalic().run()}><Italic size={15} /></button>
      <button className="icon-button" title={t("bulletList")} disabled={disabled} onClick={() => editor?.chain().focus().toggleBulletList().run()}><List size={15} /></button>
      <button className="icon-button" title={t("addLink")} disabled={disabled} onClick={() => { const href = window.prompt(t("linkUrl")); if (href) editor?.chain().focus().setLink({ href }).run(); }}><Link2 size={15} /></button>
      <span className="toolbar-separator" aria-hidden="true" />
      <label className="compact-field"><span>{t("fontSize")}</span><select aria-label={`${block.title} ${t("fontSize")}`} disabled={disabled} value={fontSizeRole} onChange={(event) => updateStyle("fontSizeRole", event.target.value)}><option value="review-10">10 pt</option><option value="review-11">11 pt</option></select></label>
      <label className="compact-field"><span>{t("lineHeight")}</span><select aria-label={`${block.title} ${t("lineHeight")}`} disabled={disabled} value={lineHeightRole} onChange={(event) => updateStyle("lineHeightRole", event.target.value)}>{LINE_HEIGHT_ROLES.map((role) => <option key={role} value={role}>{role}</option>)}</select></label>
      {TEXT_ALIGNMENTS.map(({ value, icon: Icon }) => <button key={value} className="icon-button" title={t(value === "left" ? "alignLeft" : value === "center" ? "alignCenter" : value === "right" ? "alignRight" : "justify")} aria-pressed={textAlign === value} disabled={disabled} onClick={() => setAlignment(value)}><Icon size={15} /></button>)}
    </div>
    <EditorContent editor={editor} className="review-rich-text" />
  </article>;
}

function overlaps(a: PageOneElement, b: PageOneElement): boolean {
  return a.row < b.row + b.row_span && b.row < a.row + a.row_span && a.x < b.x + b.w && b.x < a.x + a.w;
}

function isEditableTarget(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && Boolean(target.closest("input, textarea, select, [contenteditable='true']"));
}

function elementLabel(id: string, blocks: ReviewBlock[], historicalTitle: string, footnoteLabel: string): string {
  if (id === "historical_performance") return historicalTitle;
  if (id === "footnote:historical") return footnoteLabel;
  return blocks.find((candidate) => `review:${candidate.block_id}` === id)?.title ?? id;
}

const PREVIEW_OVERFLOW_TOLERANCE_PX = 0.5;
const PREVIEW_DOCUMENT_STYLE = `
  html, body {
    width: 210mm !important;
    min-width: 210mm !important;
    max-width: 210mm !important;
    height: 297mm !important;
    min-height: 297mm !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
  }
  .report-document {
    width: 210mm !important;
    height: 297mm !important;
    margin: 0 !important;
  }
  .report-page[data-page="1"] {
    width: 210mm !important;
    min-width: 210mm !important;
    max-width: 210mm !important;
    height: 297mm !important;
    min-height: 297mm !important;
    max-height: 297mm !important;
    margin: 0 !important;
    overflow: hidden !important;
    transform: scale(var(--review-preview-scale, 1)) !important;
    transform-origin: top left !important;
  }
  .report-page:not([data-page="1"]) { display: none !important; }
`;

function preparePreviewDocument(document: Document): HTMLElement | null {
  const page = document.querySelector<HTMLElement>('[data-page="1"]');
  if (!page) return null;
  document.querySelectorAll<HTMLElement>(".report-page").forEach((candidate) => {
    if (candidate !== page) candidate.remove();
  });
  if (!document.querySelector("style[data-review-preview]")) {
    const style = document.createElement("style");
    style.dataset.reviewPreview = "true";
    style.textContent = PREVIEW_DOCUMENT_STYLE;
    document.head.append(style);
  }
  return page;
}

function pageOnePreviewHtml(html: string): string {
  if (!html) return "";
  const document = new DOMParser().parseFromString(html, "text/html");
  preparePreviewDocument(document);
  return `<!doctype html>${document.documentElement.outerHTML}`;
}

function fitPreviewPage(iframe: HTMLIFrameElement): void {
  const document = iframe.contentDocument;
  if (!document) return;
  const page = preparePreviewDocument(document);
  if (!page) return;
  page.style.setProperty("--review-preview-scale", "1");
  const pageRect = page.getBoundingClientRect();
  if (iframe.clientWidth <= 0 || pageRect.width <= 0 || pageRect.height <= 0) return;
  const scale = iframe.clientWidth / pageRect.width;
  page.style.setProperty("--review-preview-scale", String(scale));
  iframe.style.height = `${pageRect.height * scale}px`;
}

function hasHorizontalScrollOverflow(node: HTMLElement): boolean {
  return [node, ...node.querySelectorAll<HTMLElement>("*")].some((candidate) => (
    candidate.scrollWidth > candidate.clientWidth + PREVIEW_OVERFLOW_TOLERANCE_PX
  ));
}

function physicallyOverlaps(left: DOMRect, right: DOMRect): boolean {
  return (
    left.right > right.left + PREVIEW_OVERFLOW_TOLERANCE_PX
    && right.right > left.left + PREVIEW_OVERFLOW_TOLERANCE_PX
    && left.bottom > right.top + PREVIEW_OVERFLOW_TOLERANCE_PX
    && right.bottom > left.top + PREVIEW_OVERFLOW_TOLERANCE_PX
  );
}

/** Keep the editor warning in step with the export preflight, including clipped wide content. */
export function markPreviewOverflows(document: Document): void {
  const page = document.querySelector<HTMLElement>('[data-page="1"]');
  if (!page) return;
  const footer = page.querySelector<HTMLElement>(".page-footer");
  const footnote = page.querySelector<HTMLElement>('[data-layout-id="footnote:historical"]');
  const pageBody = page.querySelector<HTMLElement>(".page-body");
  const pageRect = page.getBoundingClientRect();
  const bodyRect = pageBody?.getBoundingClientRect() ?? pageRect;
  const footerTop = footer?.getBoundingClientRect().top ?? pageRect.bottom;
  const footnoteTop = footnote?.getBoundingClientRect().top ?? footerTop;
  const bodySafeBottom = Math.min(footerTop, footnoteTop);

  const layoutNodes = [...page.querySelectorAll<HTMLElement>("[data-layout-id]")];
  const rects = new Map(layoutNodes.map((node) => [node, node.getBoundingClientRect()]));
  layoutNodes.forEach((node) => {
    node.removeAttribute("data-layout-overflow");
    const rect = rects.get(node)!;
    const horizontalBoundary = node.closest(".page-body") ? bodyRect : pageRect;
    const verticalBoundary = node === footnote ? footerTop : bodySafeBottom;
    const outsideHorizontalSafeArea = (
      rect.left < horizontalBoundary.left - PREVIEW_OVERFLOW_TOLERANCE_PX
      || rect.right > horizontalBoundary.right + PREVIEW_OVERFLOW_TOLERANCE_PX
    );
    if (
      rect.bottom > verticalBoundary + PREVIEW_OVERFLOW_TOLERANCE_PX
      || outsideHorizontalSafeArea
      || hasHorizontalScrollOverflow(node)
    ) {
      node.setAttribute("data-layout-overflow", "true");
    }
  });
  layoutNodes.forEach((left, index) => {
    layoutNodes.slice(index + 1).forEach((right) => {
      if (physicallyOverlaps(rects.get(left)!, rects.get(right)!)) {
        left.setAttribute("data-layout-overflow", "true");
        right.setAttribute("data-layout-overflow", "true");
      }
    });
  });
}

function PreviewPane({ html, busy, error, collapsed, onToggle, selectedId, onSelect, onArrow }: { html: string; busy: boolean; error: string; collapsed: boolean; onToggle: () => void; selectedId: string; onSelect: (id: string) => void; onArrow: (direction: "left" | "right" | "up" | "down") => void }) {
  const { t } = useLocale();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const contentId = useId();
  const pageOneHtml = useMemo(() => pageOnePreviewHtml(html), [html]);
  const resizePreview = useCallback(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    fitPreviewPage(iframe);
  }, []);
  const bindPreview = useCallback(() => {
    const document = iframeRef.current?.contentDocument;
    if (!document) return;
    preparePreviewDocument(document);
    resizePreview();
    document.querySelectorAll("[data-layout-id]").forEach((node) => {
      if (node.getAttribute("data-layout-id") === selectedId) node.setAttribute("data-layout-selected", "true");
      else node.removeAttribute("data-layout-selected");
    });
    void (async () => {
      await (document.fonts?.ready ?? Promise.resolve());
      await Promise.all([...document.images].map((image) => {
        if (!image.complete) {
          return new Promise<void>((resolve) => {
            image.addEventListener("load", () => resolve(), { once: true });
            image.addEventListener("error", () => resolve(), { once: true });
          });
        }
        return typeof image.decode === "function" ? image.decode().catch(() => undefined) : Promise.resolve();
      }));
      if (iframeRef.current?.contentDocument === document) {
        resizePreview();
        markPreviewOverflows(document);
      }
    })();
    document.onclick = (event) => {
      const target = event.target && "closest" in event.target
        ? (event.target as HTMLElement).closest<HTMLElement>("[data-layout-id]")
        : null;
      if (!target?.dataset.layoutId) return;
      event.preventDefault();
      onSelect(target.dataset.layoutId);
    };
    document.onkeydown = (event) => {
      const direction = ({ ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" } as const)[event.key as "ArrowLeft"];
      if (!direction) return;
      event.preventDefault();
      onArrow(direction);
    };
  }, [onArrow, onSelect, resizePreview, selectedId]);
  useEffect(bindPreview, [bindPreview, pageOneHtml]);
  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    const handleResize = () => {
      resizePreview();
      const document = iframe.contentDocument;
      if (document) markPreviewOverflows(document);
    };
    window.addEventListener("resize", handleResize);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(handleResize);
    observer?.observe(iframe);
    return () => {
      window.removeEventListener("resize", handleResize);
      observer?.disconnect();
    };
  }, [resizePreview]);
  return <section className="review-preview-pane" aria-label={t("livePreview")}>
    <header><span><Eye size={16} /> {t("livePreview")}</span><div className="review-preview-header-actions">{busy && <small>{t("updatingPreview")}</small>}<button type="button" className="icon-button review-preview-toggle" aria-label={t(collapsed ? "expandPreview" : "collapsePreview")} title={t(collapsed ? "expandPreview" : "collapsePreview")} aria-expanded={!collapsed} aria-controls={contentId} onClick={onToggle}>{collapsed ? <ChevronLeft size={17} /> : <ChevronRight size={17} />}</button></div></header>
    <div id={contentId} className="review-preview-content">{error ? <div className="review-preview-error" role="status">{error}</div> : pageOneHtml ? <iframe ref={iframeRef} title={t("livePreview")} sandbox="allow-same-origin" srcDoc={pageOneHtml} onLoad={bindPreview} /> : <div className="review-preview-placeholder">{t("updatingPreview")}</div>}</div>
  </section>;
}

export function ReviewCanvas({ blocks, presentation, historicalFootnote, historicalTitle, disabled, previewHtml, previewBusy, previewError, onBlocksChange, onPresentationChange, onHistoricalFootnoteChange }: { blocks: ReviewBlock[]; presentation: PageOnePresentation; historicalFootnote: string; historicalTitle: string; disabled: boolean; previewHtml: string; previewBusy: boolean; previewError: string; onBlocksChange: (blocks: ReviewBlock[]) => void; onPresentationChange: (presentation: PageOnePresentation) => void; onHistoricalFootnoteChange: (value: string) => void }) {
  const { t } = useLocale();
  const [selectedId, setSelectedId] = useState(() => `review:${blocks[0]?.block_id ?? "summary"}`);
  const [mobilePane, setMobilePane] = useState<"edit" | "preview">("edit");
  const [previewCollapsed, setPreviewCollapsed] = useState(false);
  const [footnoteParagraph, setFootnoteParagraph] = useState(0);
  const elements = presentation.page_one.elements;
  const selectedElement = elements.find((element) => element.id === selectedId) ?? elements[0];
  const reviewElements = elements.filter((element) => element.id.startsWith("review:"));
  const canMoveHorizontal = useCallback((delta: -1 | 1): boolean => {
    if (!selectedElement?.id.startsWith("review:")) return false;
    const candidate = { ...selectedElement, x: selectedElement.x + delta };
    if (candidate.x < 0 || candidate.x + candidate.w > GRID_COLUMNS) return false;
    return !reviewElements.some((element) => element.id !== candidate.id && overlaps(candidate, element));
  }, [reviewElements, selectedElement]);
  const canMoveVertical = useCallback((delta: -1 | 1): boolean => {
    if (!selectedElement) return false;
    if (selectedElement.id === "footnote:historical") {
      const next = (selectedElement.bottom_nudge_steps ?? 0) - delta;
      return next >= MIN_FOOTNOTE_NUDGE_STEPS && next <= MAX_FOOTNOTE_NUDGE_STEPS;
    }
    const next = selectedElement.vertical_nudge_steps + delta;
    return next >= MIN_VERTICAL_NUDGE_STEPS && next <= MAX_VERTICAL_NUDGE_STEPS;
  }, [selectedElement]);
  const move = useCallback((direction: "left" | "right" | "up" | "down") => {
    if (disabled || !selectedElement) return;
    const horizontalDelta = direction === "left" ? -1 : direction === "right" ? 1 : 0;
    const verticalDelta = direction === "up" ? -1 : direction === "down" ? 1 : 0;
    if (horizontalDelta && !canMoveHorizontal(horizontalDelta as -1 | 1)) return;
    if (verticalDelta && !canMoveVertical(verticalDelta as -1 | 1)) return;
    const nextElements = elements.map((element) => {
      if (element.id !== selectedElement.id) return element;
      if (horizontalDelta) return { ...element, x: element.x + horizontalDelta };
      if (element.id === "footnote:historical") return { ...element, bottom_nudge_steps: (element.bottom_nudge_steps ?? 0) - verticalDelta };
      return { ...element, vertical_nudge_steps: element.vertical_nudge_steps + verticalDelta };
    });
    onPresentationChange({ ...presentation, page_one: { elements: nextElements } });
  }, [canMoveHorizontal, canMoveVertical, disabled, elements, onPresentationChange, presentation, selectedElement]);
  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (isEditableTarget(event.target)) return;
    const direction = ({ ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" } as const)[event.key as "ArrowLeft"];
    if (!direction) return;
    event.preventDefault();
    move(direction);
  };
  const layout: Layout[] = blocks.map((block) => {
    const element = elements.find((candidate) => candidate.id === `review:${block.block_id}`);
    return { i: block.block_id, x: element?.x ?? block.x, y: element?.row ?? block.y, w: element?.w ?? block.w, h: element?.row_span ?? block.h, static: true };
  });
  const historicalElement = elements.find((element) => element.id === "historical_performance");
  const updateHistoricalTableStyle = (change: Pick<PageOneElement, "table_font_size_role"> | Pick<PageOneElement, "table_line_height_role">) => {
    if (!historicalElement) return;
    onPresentationChange({
      ...presentation,
      page_one: {
        elements: elements.map((element) => element.id === historicalElement.id ? { ...element, ...change } : element),
      },
    });
  };
  const footnoteElement = elements.find((element) => element.id === "footnote:historical");
  const footnoteParagraphs = historicalFootnoteParagraphs(historicalFootnote);
  const activeFootnoteParagraph = Math.min(footnoteParagraph, footnoteParagraphs.length - 1);
  useEffect(() => {
    setFootnoteParagraph((index) => Math.min(index, footnoteParagraphs.length - 1));
  }, [footnoteParagraphs.length]);
  useEffect(() => {
    if (!elements.some((element) => element.id === selectedId)) {
      setSelectedId(elements[0]?.id ?? "");
    }
  }, [elements, selectedId]);
  const activeFootnoteStyle = footnoteElement?.paragraph_styles?.find((style) => style.paragraph_index === activeFootnoteParagraph) ?? { paragraph_index: activeFootnoteParagraph, font_size_role: "footnote-8" as const, line_height_role: "1.2" as const, text_align: "left" as const };
  const updateFootnoteStyle = (change: Partial<FootnoteParagraphStyle>) => {
    if (!footnoteElement) return;
    const styles = [...(footnoteElement.paragraph_styles ?? [])];
    const index = styles.findIndex((style) => style.paragraph_index === activeFootnoteParagraph);
    const next = { ...activeFootnoteStyle, ...change, paragraph_index: activeFootnoteParagraph };
    if (index >= 0) styles[index] = next;
    else styles.push(next);
    onPresentationChange({ ...presentation, page_one: { elements: elements.map((element) => element.id === footnoteElement.id ? { ...element, paragraph_styles: styles.sort((left, right) => left.paragraph_index - right.paragraph_index) } : element) } });
  };
  const updateFootnoteText = (value: string) => {
    const paragraphCount = historicalFootnoteParagraphs(value).length;
    if (footnoteElement?.paragraph_styles?.some((style) => style.paragraph_index >= paragraphCount)) {
      onPresentationChange(retargetHistoricalFootnoteStyles(presentation, value));
    }
    setFootnoteParagraph((index) => Math.min(index, paragraphCount - 1));
    onHistoricalFootnoteChange(value);
  };
  const selectedLabel = selectedElement ? elementLabel(selectedElement.id, blocks, historicalTitle, t("historicalFootnote")) : "";
  return <div className="page-one-editor" tabIndex={0} onKeyDown={handleKeyDown}>
    <div className="review-pane-switch" role="group" aria-label={t("reviewPane")}><button aria-pressed={mobilePane === "edit"} onClick={() => setMobilePane("edit")}><Pencil size={16} /> {t("edit")}</button><button aria-pressed={mobilePane === "preview"} onClick={() => setMobilePane("preview")}><Eye size={16} /> {t("preview")}</button></div>
    <div className={`page-one-editor-grid mobile-${mobilePane}${previewCollapsed ? " preview-collapsed" : ""}`}>
      <section className="page-one-edit-pane">
        <div className="layout-nudge-controls" aria-label={t("layoutControls")}>
          <span>{t("selectedModule")}: <strong>{selectedLabel}</strong></span>
          <div>
            <button className="icon-button" aria-label={t("moveLeft")} title={t("moveLeft")} aria-keyshortcuts="ArrowLeft" disabled={disabled || !canMoveHorizontal(-1)} onClick={() => move("left")}><ArrowLeft size={17} /></button>
            <button className="icon-button" aria-label={t("moveUp")} title={t("moveUp")} aria-keyshortcuts="ArrowUp" disabled={disabled || !canMoveVertical(-1)} onClick={() => move("up")}><ArrowUp size={17} /></button>
            <button className="icon-button" aria-label={t("moveDown")} title={t("moveDown")} aria-keyshortcuts="ArrowDown" disabled={disabled || !canMoveVertical(1)} onClick={() => move("down")}><ArrowDown size={17} /></button>
            <button className="icon-button" aria-label={t("moveRight")} title={t("moveRight")} aria-keyshortcuts="ArrowRight" disabled={disabled || !canMoveHorizontal(1)} onClick={() => move("right")}><ArrowRight size={17} /></button>
          </div>
          <small>{t("nudgeHelp")}</small>
        </div>
        <div className="review-builder">
          <div className="review-builder-tools"><span>{t("canvasHelp")}</span></div>
          <TwelveColumnGrid className="review-grid" layout={layout} cols={GRID_COLUMNS} rowHeight={34} margin={[16, 16]} containerPadding={[0, 0]} compactType={null} preventCollision isDraggable={false} isResizable={false}>
            {blocks.map((block) => <div key={block.block_id} onFocus={() => setSelectedId(`review:${block.block_id}`)}><RichTextBlock block={block} disabled={disabled} selected={selectedId === `review:${block.block_id}`} onSelect={() => setSelectedId(`review:${block.block_id}`)} onChange={(content) => onBlocksChange(blocks.map((item) => item.block_id === block.block_id ? { ...item, content } : item))} /></div>)}
          </TwelveColumnGrid>
        </div>
        <section className={`page-one-fixed-module${selectedId === "historical_performance" ? " selected" : ""}`} data-layout-id="historical_performance" onFocusCapture={() => setSelectedId("historical_performance")}>
          <button type="button" className="page-one-fixed-module-select" onClick={() => setSelectedId("historical_performance")}><strong>{historicalTitle}</strong><span>{t("readOnlyValues")}</span></button>
          <div className="historical-table-style-controls">
            <label>{t("fontSize")}<select aria-label={t("historicalTableFontSize")} disabled={disabled} value={historicalElement?.table_font_size_role ?? "history-10"} onChange={(event) => updateHistoricalTableStyle({ table_font_size_role: event.target.value as HistoricalTableFontSizeRole })}>{HISTORICAL_TABLE_FONT_SIZE_ROLES.map((role) => <option key={role} value={role}>{role.replace("history-", "")} pt</option>)}</select></label>
            <label>{t("lineHeight")}<select aria-label={t("historicalTableLineHeight")} disabled={disabled} value={historicalElement?.table_line_height_role ?? "1.2"} onChange={(event) => updateHistoricalTableStyle({ table_line_height_role: event.target.value as LineHeightRole })}>{LINE_HEIGHT_ROLES.map((role) => <option key={role} value={role}>{role}</option>)}</select></label>
          </div>
        </section>
        <section className={`historical-footnote-editor${selectedId === "footnote:historical" ? " selected" : ""}`} data-layout-id="footnote:historical" onClick={() => setSelectedId("footnote:historical")}>
          <header><strong>{t("historicalFootnote")}</strong><span>{t("sharedWithFootnotes")}</span></header>
          <textarea aria-label={t("historicalFootnote")} value={historicalFootnote} disabled={disabled} onChange={(event) => updateFootnoteText(event.target.value)} />
          <div className="footnote-style-controls">
            <label>{t("paragraph")}<select disabled={disabled} value={activeFootnoteParagraph} onChange={(event) => setFootnoteParagraph(Number(event.target.value))}>{footnoteParagraphs.map((paragraph, index) => <option key={`${index}-${paragraph.slice(0, 12)}`} value={index}>{index + 1}</option>)}</select></label>
            <label>{t("fontSize")}<select disabled={disabled} value={activeFootnoteStyle.font_size_role} onChange={(event) => updateFootnoteStyle({ font_size_role: event.target.value as FootnoteFontSizeRole })}>{FOOTNOTE_FONT_SIZE_ROLES.map((role) => <option key={role} value={role}>{role.replace("footnote-", "")} pt</option>)}</select></label>
            <label>{t("lineHeight")}<select disabled={disabled} value={activeFootnoteStyle.line_height_role} onChange={(event) => updateFootnoteStyle({ line_height_role: event.target.value as LineHeightRole })}>{LINE_HEIGHT_ROLES.map((role) => <option key={role} value={role}>{role}</option>)}</select></label>
            <label>{t("alignment")}<select disabled={disabled} value={activeFootnoteStyle.text_align} onChange={(event) => updateFootnoteStyle({ text_align: event.target.value as ReviewTextAlign })}>{TEXT_ALIGNMENTS.map(({ value }) => <option key={value} value={value}>{t(value === "left" ? "alignLeft" : value === "center" ? "alignCenter" : value === "right" ? "alignRight" : "justify")}</option>)}</select></label>
          </div>
        </section>
      </section>
      <PreviewPane html={previewHtml} busy={previewBusy} error={previewError} collapsed={previewCollapsed} onToggle={() => setPreviewCollapsed((value) => !value)} selectedId={selectedId} onSelect={(id) => { setSelectedId(id); setMobilePane("edit"); }} onArrow={move} />
    </div>
  </div>;
}
