import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  Eye,
  GripVertical,
  Maximize2,
  Minimize2,
  Pencil,
  Plus,
} from "lucide-react";
import GridLayout, { WidthProvider, type Layout } from "react-grid-layout";
import { useLocale } from "../../i18n";
import { MarkerTextarea } from "../../components/SuperscriptMarkerControl";
import { BoundedNumberInput, RichTypographyEditor, TextStyleControls, textStyleProperties } from "./RichTypographyEditor";
import {
  FOOTNOTE_BODY_STYLE,
  GRID_COLUMNS,
  HISTORY_BODY_STYLE,
  HISTORY_HEADER_STYLE,
  HISTORY_TITLE_STYLE,
  MAX_OFFSET_Y_PT,
  MAX_REVIEW_PAGES,
  MAX_VERTICAL_NUDGE_STEPS,
  MIN_OFFSET_Y_PT,
  MIN_VERTICAL_NUDGE_STEPS,
  REVIEW_BODY_STYLE,
  REVIEW_TITLE_STYLE,
  TYPOGRAPHY_LIMITS,
  historicalFootnoteParagraphs,
  legacyReviewBlocks,
  pageOnePresentation,
  plainTextToRichHtml,
  retargetHistoricalFootnoteStyles,
  richHtmlToPlainText,
  updateElement,
  updateHistoricalGroup,
  type FootnoteFontSizeRole,
  type FootnoteParagraphStyle,
  type HistoricalTableFontSizeRole,
  type LineHeightRole,
  type PageOneElement,
  type PageOnePresentation,
  type ReviewBlock,
  type ReviewFontSizeRole,
  type ReviewTextAlign,
  type TextStyle,
} from "./reviewPresentation";

export {
  historicalFootnoteParagraphs,
  legacyReviewBlocks,
  pageOnePresentation,
  retargetHistoricalFootnoteStyles,
  richHtmlToPlainText,
};
export type {
  FootnoteFontSizeRole,
  FootnoteParagraphStyle,
  HistoricalTableFontSizeRole,
  LineHeightRole,
  PageOneElement,
  PageOnePresentation,
  ReviewBlock,
  ReviewFontSizeRole,
  ReviewTextAlign,
  TextStyle,
};

const TwelveColumnGrid = WidthProvider(GridLayout);
const GRID_ROW_HEIGHT = 34;
const GRID_GAP = 16;
const LAYOUT_PT_STEP = 6;

function overlaps(a: PageOneElement, b: PageOneElement): boolean {
  return a.row < b.row + b.row_span && b.row < a.row + a.row_span && a.x < b.x + b.w && b.x < a.x + a.w;
}

function isEditableTarget(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && Boolean(target.closest("input, textarea, select, button, a, [contenteditable='true']"));
}

function elementLabel(id: string, blocks: ReviewBlock[], historicalTitle: string, footnoteLabel: string): string {
  if (id === "historical_performance") return historicalTitle;
  if (id === "footnote:historical") return footnoteLabel;
  return blocks.find((candidate) => `review:${candidate.block_id}` === id)?.title ?? id;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function DragHandle({ disabled, label }: { disabled: boolean; label: string }) {
  return <span
    className={`review-drag-handle${disabled ? " disabled" : ""}`}
    aria-label={label}
    aria-disabled={disabled}
    title={label}
    onClick={(event) => event.stopPropagation()}
  ><GripVertical size={18} /></span>;
}

function ModuleHeader({
  title,
  width,
  disabled,
  expanded,
  titleStyle,
  onExpand,
  trailing,
}: {
  title: string;
  width: number;
  disabled: boolean;
  expanded: boolean;
  titleStyle?: TextStyle;
  onExpand: (event: ReactMouseEvent<HTMLButtonElement>) => void;
  trailing?: ReactNode;
}) {
  const { t } = useLocale();
  return <header>
    <DragHandle disabled={disabled || expanded} label={`${t("dragBlock")}: ${title}`} />
    <strong className="locked-module-title" style={titleStyle ? textStyleProperties(titleStyle) : undefined}>{title}</strong>
    {trailing}
    <span className="module-grid-width">{width}/{GRID_COLUMNS}</span>
    <button
      type="button"
      className="icon-button module-expand-button"
      aria-label={t(expanded ? "closeInspector" : "openInspector", { title })}
      title={t(expanded ? "closeInspector" : "openInspector", { title })}
      aria-expanded={expanded}
      onClick={onExpand}
    >{expanded ? <Minimize2 size={16} /> : <Maximize2 size={16} />}</button>
  </header>;
}

function ReviewBlockEditor({
  block,
  element,
  disabled,
  selected,
  expanded,
  onSelect,
  onExpand,
  onTitleChange,
  onChange,
  onElementChange,
}: {
  block: ReviewBlock;
  element: PageOneElement;
  disabled: boolean;
  selected: boolean;
  expanded: boolean;
  onSelect: () => void;
  onExpand: (trigger?: HTMLElement) => void;
  onTitleChange: (title: string) => void;
  onChange: (content: string) => void;
  onElementChange: (change: Partial<PageOneElement>) => void;
}) {
  const { t } = useLocale();
  const titleStyle = element.title_style ?? REVIEW_TITLE_STYLE;
  const bodyStyle = element.body_style ?? REVIEW_BODY_STYLE;
  return <article
    className={`review-block page-one-module-shell${selected ? " selected" : ""}${expanded ? " is-expanded" : ""}`}
    data-layout-id={element.id}
    role={expanded ? "dialog" : undefined}
    aria-modal={expanded ? true : undefined}
    aria-label={expanded ? t("moduleInspector", { title: block.title }) : undefined}
    tabIndex={0}
    onClick={(event) => {
      onSelect();
      if (!expanded && !isEditableTarget(event.target)) onExpand(event.currentTarget);
    }}
  >
    <ModuleHeader
      title={block.title}
      width={element.w}
      disabled={disabled}
      expanded={expanded}
      titleStyle={titleStyle}
      onExpand={(event) => { event.stopPropagation(); onExpand(event.currentTarget); }}
    />
    {expanded && <div className="module-title-style-controls" onClick={(event) => event.stopPropagation()}>
      <h4>{t("moduleTitleStyle")}</h4>
      <label className="review-title-field">
        <span>{t("moduleTitle")}</span>
        <input
          className="review-block-title"
          aria-label={t("blockTitle", { id: block.block_id })}
          value={block.title}
          maxLength={200}
          disabled={disabled}
          onChange={(event) => {
            if (event.target.value.trim()) onTitleChange(event.target.value);
          }}
        />
      </label>
      <BoundedNumberInput
        label={t("titleContentSpacing")}
        value={titleStyle.space_after_pt}
        {...TYPOGRAPHY_LIMITS.spacing}
        disabled={disabled}
        onCommit={(space_after_pt) => onElementChange({ title_style: { ...titleStyle, space_after_pt } })}
      />
      <BoundedNumberInput
        label={`${t("moduleTitle")} ${t("indentLevel")}`}
        value={titleStyle.indent_level ?? 0}
        {...TYPOGRAPHY_LIMITS.indent}
        disabled={disabled}
        onCommit={(indent_level) => onElementChange({ title_style: { ...titleStyle, indent_level } })}
      />
    </div>}
    <RichTypographyEditor
      label={block.title}
      value={block.content}
      defaultStyle={bodyStyle}
      disabled={disabled}
      showAdvanced={expanded}
      onChange={onChange}
      onDefaultStyleChange={(change) => onElementChange({ body_style: { ...bodyStyle, ...change } })}
    />
  </article>;
}

function HistoricalEditor({ historicalTitle, element, disabled, selected, expanded, onSelect, onExpand, onChange }: {
  historicalTitle: string;
  element: PageOneElement;
  disabled: boolean;
  selected: boolean;
  expanded: boolean;
  onSelect: () => void;
  onExpand: (trigger?: HTMLElement) => void;
  onChange: (change: Partial<PageOneElement>) => void;
}) {
  const { t } = useLocale();
  const titleStyle = element.title_style ?? HISTORY_TITLE_STYLE;
  const headerStyle = element.header_style ?? HISTORY_HEADER_STYLE;
  const bodyStyle = element.body_style ?? HISTORY_BODY_STYLE;
  return <section
    className={`page-one-fixed-module page-one-module-shell${selected ? " selected" : ""}${expanded ? " is-expanded" : ""}`}
    data-layout-id="historical_performance"
    role={expanded ? "dialog" : undefined}
    aria-modal={expanded ? true : undefined}
    aria-label={expanded ? t("moduleInspector", { title: historicalTitle }) : undefined}
    tabIndex={0}
    onFocusCapture={onSelect}
    onClick={(event) => {
      onSelect();
      if (!expanded && !isEditableTarget(event.target)) onExpand(event.currentTarget);
    }}
  >
    <ModuleHeader title={historicalTitle} width={element.w} disabled={disabled} expanded={expanded} titleStyle={titleStyle} onExpand={(event) => { event.stopPropagation(); onExpand(event.currentTarget); }} trailing={<span className="read-only-badge">{t("readOnlyValues")}</span>} />
    <div className="historical-style-summary">{t("historyStyleSummary")}</div>
    {expanded && <div className="historical-table-style-controls advanced-module-controls">
      <section><h4>{t("historyTitleStyle")}</h4><BoundedNumberInput label={t("titleContentSpacing")} value={titleStyle.space_after_pt} {...TYPOGRAPHY_LIMITS.spacing} disabled={disabled} onCommit={(space_after_pt) => onChange({ title_style: { ...titleStyle, space_after_pt } })} /></section>
      <section><h4>{t("historyHeaderStyle")}</h4><TextStyleControls idPrefix={t("historyHeaderStyle")} value={headerStyle} disabled={disabled} showParagraphSpacing={false} onChange={(change) => onChange({ header_style: { ...headerStyle, ...change } })} /></section>
      <section><h4>{t("historyBodyStyle")}</h4><TextStyleControls idPrefix={t("historyBodyStyle")} value={bodyStyle} disabled={disabled} showParagraphSpacing={false} onChange={(change) => onChange({ body_style: { ...bodyStyle, ...change } })} /></section>
      <section className="table-padding-control"><h4>{t("tableSpacing")}</h4><BoundedNumberInput label={t("cellPaddingY")} value={element.cell_padding_y_pt ?? 2} {...TYPOGRAPHY_LIMITS.spacing} disabled={disabled} onCommit={(cell_padding_y_pt) => onChange({ cell_padding_y_pt })} /></section>
    </div>}
  </section>;
}

function HistoricalFootnoteEditor({ element, disabled, selected, expanded, onSelect, onExpand, onChange, onTextChange }: {
  element: PageOneElement;
  disabled: boolean;
  selected: boolean;
  expanded: boolean;
  onSelect: () => void;
  onExpand: (trigger?: HTMLElement) => void;
  onChange: (change: Partial<PageOneElement>) => void;
  onTextChange: (value: string) => void;
}) {
  const { t } = useLocale();
  const style = element.body_style ?? FOOTNOTE_BODY_STYLE;
  return <section
    className={`historical-footnote-editor page-one-module-shell${selected ? " selected" : ""}${expanded ? " is-expanded" : ""}`}
    data-layout-id="footnote:historical"
    role={expanded ? "dialog" : undefined}
    aria-modal={expanded ? true : undefined}
    aria-label={expanded ? t("moduleInspector", { title: t("historicalFootnote") }) : undefined}
    tabIndex={0}
    onClick={(event) => {
      onSelect();
      if (!expanded && !isEditableTarget(event.target)) onExpand(event.currentTarget);
    }}
  >
    <ModuleHeader title={t("historicalFootnote")} width={element.w} disabled={disabled} expanded={expanded} onExpand={(event) => { event.stopPropagation(); onExpand(event.currentTarget); }} trailing={<span className="read-only-badge">{t("sharedWithFootnotes")}</span>} />
    {expanded ? <RichTypographyEditor
      label={t("historicalFootnote")}
      value={element.content_html ?? "<p></p>"}
      defaultStyle={style}
      disabled={disabled}
      showAdvanced
      onChange={(content_html) => {
        onChange({ content_html });
        onTextChange(richHtmlToPlainText(content_html));
      }}
      onDefaultStyleChange={(change) => onChange({ body_style: { ...style, ...change } })}
    /> : <MarkerTextarea
      aria-label={t("historicalFootnote")}
      value={richHtmlToPlainText(element.content_html ?? "")}
      disabled={disabled}
      onValueChange={(text) => {
        onChange({ content_html: plainTextToRichHtml(text) });
        onTextChange(text);
      }}
    />}
  </section>;
}

const PREVIEW_OVERFLOW_TOLERANCE_PX = 0.5;
const MINOR_OVERFLOW_MM = 3;
const A4_HEIGHT_PT = (297 / 25.4) * 72;
const PREVIEW_DOCUMENT_STYLE = `
  html, body {
    width: 100% !important;
    min-width: 0 !important;
    height: auto !important;
    min-height: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow-x: hidden !important;
    overflow-y: auto !important;
    background: transparent !important;
  }
  .report-document {
    width: 210mm !important;
    height: auto !important;
    margin: 0 !important;
    zoom: var(--review-preview-scale, 1) !important;
  }
  .report-page[data-section-key="month_in_review"],
  .report-page[data-review-preview-fallback="true"] {
    display: block !important;
    width: 210mm !important;
    min-width: 210mm !important;
    max-width: 210mm !important;
    height: 297mm !important;
    min-height: 297mm !important;
    max-height: 297mm !important;
    margin: 0 0 8mm !important;
    overflow: hidden !important;
  }
  .report-page:not([data-section-key="month_in_review"]):not([data-review-preview-fallback="true"]) { display: none !important; }
`;

function reviewPreviewPages(document: Document): HTMLElement[] {
  const tagged = [...document.querySelectorAll<HTMLElement>('.report-page[data-section-key="month_in_review"]')];
  if (tagged.length) return tagged;
  const fallback = document.querySelector<HTMLElement>('.report-page[data-page="1"]');
  if (fallback) fallback.dataset.reviewPreviewFallback = "true";
  return fallback ? [fallback] : [];
}

function preparePreviewDocument(document: Document): HTMLElement[] {
  const pages = reviewPreviewPages(document);
  const kept = new Set(pages);
  document.querySelectorAll<HTMLElement>(".report-page").forEach((candidate) => {
    if (!kept.has(candidate)) candidate.remove();
  });
  if (!document.querySelector("style[data-review-preview]")) {
    const style = document.createElement("style");
    style.dataset.reviewPreview = "true";
    style.textContent = PREVIEW_DOCUMENT_STYLE;
    document.head.append(style);
  }
  return pages;
}

export function pageOnePreviewHtml(html: string): string {
  if (!html) return "";
  const document = new DOMParser().parseFromString(html, "text/html");
  preparePreviewDocument(document);
  return `<!doctype html>${document.documentElement.outerHTML}`;
}

function fitPreviewPages(iframe: HTMLIFrameElement): void {
  const document = iframe.contentDocument;
  if (!document) return;
  const pages = preparePreviewDocument(document);
  const firstPage = pages[0];
  if (!firstPage) return;
  document.documentElement.style.setProperty("--review-preview-scale", "1");
  const pageRect = firstPage.getBoundingClientRect();
  if (iframe.clientWidth <= 0 || pageRect.width <= 0) return;
  document.documentElement.style.setProperty("--review-preview-scale", String(iframe.clientWidth / pageRect.width));
}

function hasHorizontalScrollOverflow(node: HTMLElement): boolean {
  return [node, ...node.querySelectorAll<HTMLElement>("*")].some((candidate) => candidate.scrollWidth > candidate.clientWidth + PREVIEW_OVERFLOW_TOLERANCE_PX);
}

function physicallyOverlaps(left: DOMRect, right: DOMRect): boolean {
  return left.right > right.left + PREVIEW_OVERFLOW_TOLERANCE_PX
    && right.right > left.left + PREVIEW_OVERFLOW_TOLERANCE_PX
    && left.bottom > right.top + PREVIEW_OVERFLOW_TOLERANCE_PX
    && right.bottom > left.top + PREVIEW_OVERFLOW_TOLERANCE_PX;
}

/** Mirror server preflight visually: orange for <=3 mm vertical tolerance, red for blockers. */
export function markPreviewOverflows(document: Document): void {
  reviewPreviewPages(document).forEach((page) => {
    const footer = page.querySelector<HTMLElement>(".page-footer");
    const footnote = page.querySelector<HTMLElement>('[data-layout-id="footnote:historical"]');
    const pageBody = page.querySelector<HTMLElement>(".page-body");
    const pageRect = page.getBoundingClientRect();
    const bodyRect = pageBody?.getBoundingClientRect() ?? pageRect;
    const footerTop = footer?.getBoundingClientRect().top ?? pageRect.bottom;
    const footnoteTop = footnote?.getBoundingClientRect().top ?? footerTop;
    const bodySafeBottom = Math.min(footerTop, footnoteTop);
    const tolerancePx = (pageRect.height / 297) * MINOR_OVERFLOW_MM;
    const layoutNodes = [...page.querySelectorAll<HTMLElement>("[data-layout-id]")];
    const rects = new Map(layoutNodes.map((node) => [node, node.getBoundingClientRect()]));

    layoutNodes.forEach((node) => {
      node.removeAttribute("data-layout-warning");
      node.removeAttribute("data-layout-overflow");
      const rect = rects.get(node)!;
      const horizontalBoundary = node.closest(".page-body") ? bodyRect : pageRect;
      const verticalBoundary = node === footnote ? footerTop : bodySafeBottom;
      const horizontalOverflow = rect.left < horizontalBoundary.left - PREVIEW_OVERFLOW_TOLERANCE_PX
        || rect.right > horizontalBoundary.right + PREVIEW_OVERFLOW_TOLERANCE_PX
        || hasHorizontalScrollOverflow(node);
      const verticalOverflow = rect.bottom - verticalBoundary;
      if (horizontalOverflow || verticalOverflow > tolerancePx + PREVIEW_OVERFLOW_TOLERANCE_PX) {
        node.setAttribute("data-layout-overflow", "true");
      } else if (verticalOverflow > PREVIEW_OVERFLOW_TOLERANCE_PX) {
        node.setAttribute("data-layout-warning", "true");
      }
    });
    layoutNodes.forEach((left, index) => {
      layoutNodes.slice(index + 1).forEach((right) => {
        if (physicallyOverlaps(rects.get(left)!, rects.get(right)!)) {
          left.setAttribute("data-layout-overflow", "true");
          right.setAttribute("data-layout-overflow", "true");
          left.removeAttribute("data-layout-warning");
          right.removeAttribute("data-layout-warning");
        }
      });
    });
  });
}

export function historicalGroupDownRoomPt(document: Document): number | null {
  const footnote = document.querySelector<HTMLElement>('[data-layout-id="footnote:historical"]');
  const page = footnote?.closest<HTMLElement>(".report-page");
  if (!footnote || !page) return null;
  const pageHeightPx = page.getBoundingClientRect().height;
  if (pageHeightPx <= 0) return null;
  const footer = page.querySelector<HTMLElement>(".page-footer");
  const safeBottom = footer?.getBoundingClientRect().top ?? page.getBoundingClientRect().bottom;
  const pxPerPoint = pageHeightPx / A4_HEIGHT_PT;
  return (safeBottom - footnote.getBoundingClientRect().bottom) / pxPerPoint;
}

function PreviewPane({ html, busy, error, collapsed, onToggle, selectedId, onSelect, onArrow, onGroupDownRoomChange }: {
  html: string;
  busy: boolean;
  error: string;
  collapsed: boolean;
  onToggle: () => void;
  selectedId: string;
  onSelect: (id: string) => void;
  onArrow: (direction: "left" | "right" | "up" | "down") => void;
  onGroupDownRoomChange: (roomPt: number | null) => void;
}) {
  const { t } = useLocale();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const contentId = useId();
  const reviewHtml = useMemo(() => pageOnePreviewHtml(html), [html]);
  const resizePreview = useCallback(() => {
    const iframe = iframeRef.current;
    if (iframe) fitPreviewPages(iframe);
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
        if (!image.complete) return new Promise<void>((resolve) => {
          image.addEventListener("load", () => resolve(), { once: true });
          image.addEventListener("error", () => resolve(), { once: true });
        });
        return typeof image.decode === "function" ? image.decode().catch(() => undefined) : Promise.resolve();
      }));
      if (iframeRef.current?.contentDocument === document) {
        resizePreview();
        markPreviewOverflows(document);
        onGroupDownRoomChange(historicalGroupDownRoomPt(document));
      }
    })();
    document.onclick = (event) => {
      const target = event.target && "closest" in event.target ? (event.target as HTMLElement).closest<HTMLElement>("[data-layout-id]") : null;
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
  }, [onArrow, onGroupDownRoomChange, onSelect, resizePreview, selectedId]);
  useEffect(bindPreview, [bindPreview, reviewHtml]);
  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    const handleResize = () => {
      resizePreview();
      const document = iframe.contentDocument;
      if (document) {
        markPreviewOverflows(document);
        onGroupDownRoomChange(historicalGroupDownRoomPt(document));
      }
    };
    window.addEventListener("resize", handleResize);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(handleResize);
    observer?.observe(iframe);
    return () => {
      window.removeEventListener("resize", handleResize);
      observer?.disconnect();
    };
  }, [onGroupDownRoomChange, resizePreview]);
  return <section className="review-preview-pane" aria-label={t("livePreview")}>
    <header><span><Eye size={16} /> {t("livePreview")}</span><div className="review-preview-header-actions">{busy && <small>{t("updatingPreview")}</small>}<button type="button" className="icon-button review-preview-toggle" aria-label={t(collapsed ? "expandPreview" : "collapsePreview")} title={t(collapsed ? "expandPreview" : "collapsePreview")} aria-expanded={!collapsed} aria-controls={contentId} onClick={onToggle}>{collapsed ? <ChevronLeft size={17} /> : <ChevronRight size={17} />}</button></div></header>
    <div id={contentId} className="review-preview-content">{error ? <div className="review-preview-error" role="status">{error}</div> : reviewHtml ? <iframe ref={iframeRef} title={t("livePreview")} sandbox="allow-same-origin" srcDoc={reviewHtml} onLoad={bindPreview} /> : <div className="review-preview-placeholder">{t("updatingPreview")}</div>}</div>
  </section>;
}

function changeElementStyle(presentation: PageOnePresentation, id: string, change: Partial<PageOneElement>): PageOnePresentation {
  return updateElement(presentation, id, (element) => ({ ...element, ...change }));
}

export function ReviewCanvas({ blocks, presentation, historicalFootnote, historicalTitle, disabled, previewHtml, previewBusy, previewError, onBlocksChange, onPresentationChange, onHistoricalFootnoteChange }: {
  blocks: ReviewBlock[];
  presentation: PageOnePresentation;
  historicalFootnote: string;
  historicalTitle: string;
  disabled: boolean;
  previewHtml: string;
  previewBusy: boolean;
  previewError: string;
  onBlocksChange: (blocks: ReviewBlock[]) => void;
  onPresentationChange: (presentation: PageOnePresentation) => void;
  onHistoricalFootnoteChange: (value: string) => void;
}) {
  const { t } = useLocale();
  const [selectedId, setSelectedId] = useState(() => `review:${blocks[0]?.block_id ?? "summary"}`);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [mobilePane, setMobilePane] = useState<"edit" | "preview">("edit");
  const [previewCollapsed, setPreviewCollapsed] = useState(false);
  const [groupDownRoomPt, setGroupDownRoomPt] = useState<number | null>(null);
  const editorRoot = useRef<HTMLDivElement>(null);
  const inspectorTrigger = useRef<HTMLElement | null>(null);
  const elements = presentation.page_one.elements;
  const selectedElement = elements.find((element) => element.id === selectedId) ?? elements[0];
  const reviewElements = elements.filter((element) => element.id.startsWith("review:"));
  const historicalElement = elements.find((element) => element.id === "historical_performance");
  const footnoteElement = elements.find((element) => element.id === "footnote:historical");
  const historyPage = historicalElement?.page ?? 1;
  const pageCount = Math.max(presentation.page_one.review_page_count, historyPage);

  const closeInspector = useCallback(() => {
    setExpandedId(null);
    window.requestAnimationFrame(() => inspectorTrigger.current?.focus());
  }, []);
  const openInspector = useCallback((id: string, trigger?: HTMLElement) => {
    inspectorTrigger.current = trigger ?? null;
    setSelectedId(id);
    setExpandedId((current) => current === id ? null : id);
  }, []);
  useEffect(() => {
    if (!expandedId) return undefined;
    const panel = editorRoot.current?.querySelector<HTMLElement>(".page-one-module-shell.is-expanded");
    const focusable = () => panel ? [...panel.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], [contenteditable="true"], [tabindex]:not([tabindex="-1"])',
    )] : [];
    focusable()[0]?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeInspector();
        return;
      }
      if (event.key !== "Tab") return;
      const candidates = focusable();
      if (!candidates.length) return;
      const first = candidates[0];
      const last = candidates[candidates.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [closeInspector, expandedId]);
  useEffect(() => {
    if (!elements.some((element) => element.id === selectedId)) setSelectedId(elements[0]?.id ?? "");
    if (expandedId && !elements.some((element) => element.id === expandedId)) setExpandedId(null);
  }, [elements, expandedId, selectedId]);

  const canMoveHorizontal = useCallback((delta: -1 | 1): boolean => {
    if (!selectedElement) return false;
    const candidate = { ...selectedElement, x: selectedElement.x + delta };
    if (candidate.x < 0 || candidate.x + candidate.w > GRID_COLUMNS) return false;
    if (!selectedElement.id.startsWith("review:")) return true;
    return !reviewElements.some((element) => element.id !== candidate.id && overlaps(candidate, element));
  }, [reviewElements, selectedElement]);

  const canMoveVertical = useCallback((delta: -1 | 1): boolean => {
    if (!selectedElement) return false;
    if (selectedElement.id.startsWith("review:")) {
      const next = (selectedElement.vertical_nudge_steps ?? 0) + delta;
      return next >= MIN_VERTICAL_NUDGE_STEPS && next <= MAX_VERTICAL_NUDGE_STEPS;
    }
    if (selectedElement.id === "historical_performance") {
      const next = (historicalElement?.offset_y_pt ?? 0) + delta * LAYOUT_PT_STEP;
      if (delta > 0 && groupDownRoomPt !== null && groupDownRoomPt < LAYOUT_PT_STEP) return historyPage < MAX_REVIEW_PAGES;
      return (next >= MIN_OFFSET_Y_PT && next <= MAX_OFFSET_Y_PT) || (delta > 0 ? historyPage < MAX_REVIEW_PAGES : historyPage > 1);
    }
    const next = (footnoteElement?.gap_pt ?? 6) + delta * LAYOUT_PT_STEP;
    if (delta > 0 && groupDownRoomPt !== null && groupDownRoomPt < LAYOUT_PT_STEP) return historyPage < MAX_REVIEW_PAGES;
    return (next >= TYPOGRAPHY_LIMITS.spacing.min && next <= TYPOGRAPHY_LIMITS.spacing.max) || (delta > 0 ? historyPage < MAX_REVIEW_PAGES : historyPage > 1);
  }, [footnoteElement?.gap_pt, groupDownRoomPt, historicalElement?.offset_y_pt, historyPage, selectedElement]);

  const moveHistoryGroupToPage = useCallback((requested: number, resetSpacing = false) => {
    const page = clamp(Math.round(requested), 1, MAX_REVIEW_PAGES);
    const nextCount = Math.max(pageCount, page);
    const moved = updateHistoricalGroup(presentation, (element) => ({
      ...element,
      page,
      ...(resetSpacing && element.id === "historical_performance" ? { offset_y_pt: 0 } : {}),
      ...(resetSpacing && element.id === "footnote:historical" ? { gap_pt: 6 } : {}),
    }));
    setGroupDownRoomPt(null);
    onPresentationChange({ ...moved, page_one: { ...moved.page_one, review_page_count: nextCount } });
  }, [onPresentationChange, pageCount, presentation]);

  const move = useCallback((direction: "left" | "right" | "up" | "down") => {
    if (disabled || !selectedElement) return;
    const horizontalDelta = direction === "left" ? -1 : direction === "right" ? 1 : 0;
    const verticalDelta = direction === "up" ? -1 : direction === "down" ? 1 : 0;
    if (horizontalDelta) {
      if (!canMoveHorizontal(horizontalDelta as -1 | 1)) return;
      if (selectedElement.id === "historical_performance" || selectedElement.id === "footnote:historical") {
        onPresentationChange(updateHistoricalGroup(presentation, (element) => ({ ...element, x: element.x + horizontalDelta })));
      } else {
        onPresentationChange(updateElement(presentation, selectedElement.id, (element) => ({ ...element, x: element.x + horizontalDelta })));
      }
      return;
    }
    if (!verticalDelta || !canMoveVertical(verticalDelta as -1 | 1)) return;
    if (selectedElement.id.startsWith("review:")) {
      onPresentationChange(updateElement(presentation, selectedElement.id, (element) => ({ ...element, vertical_nudge_steps: (element.vertical_nudge_steps ?? 0) + verticalDelta })));
      return;
    }
    if (selectedElement.id === "historical_performance") {
      const offset = (historicalElement?.offset_y_pt ?? 0) + verticalDelta * LAYOUT_PT_STEP;
      const crossesRenderedPageBottom = verticalDelta > 0 && groupDownRoomPt !== null && groupDownRoomPt < LAYOUT_PT_STEP;
      if (!crossesRenderedPageBottom && offset >= MIN_OFFSET_Y_PT && offset <= MAX_OFFSET_Y_PT) {
        onPresentationChange(updateElement(presentation, selectedElement.id, (element) => ({ ...element, offset_y_pt: offset })));
        setGroupDownRoomPt((room) => room === null ? null : room - verticalDelta * LAYOUT_PT_STEP);
      } else {
        moveHistoryGroupToPage(historyPage + verticalDelta, true);
      }
      return;
    }
    const gap = (footnoteElement?.gap_pt ?? 6) + verticalDelta * LAYOUT_PT_STEP;
    const crossesRenderedPageBottom = verticalDelta > 0 && groupDownRoomPt !== null && groupDownRoomPt < LAYOUT_PT_STEP;
    if (!crossesRenderedPageBottom && gap >= TYPOGRAPHY_LIMITS.spacing.min && gap <= TYPOGRAPHY_LIMITS.spacing.max) {
      onPresentationChange(updateElement(presentation, selectedElement.id, (element) => ({ ...element, gap_pt: gap })));
      setGroupDownRoomPt((room) => room === null ? null : room - verticalDelta * LAYOUT_PT_STEP);
    } else {
      moveHistoryGroupToPage(historyPage + verticalDelta, true);
    }
  }, [canMoveHorizontal, canMoveVertical, disabled, footnoteElement?.gap_pt, groupDownRoomPt, historicalElement?.offset_y_pt, historyPage, moveHistoryGroupToPage, onPresentationChange, presentation, selectedElement]);

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (isEditableTarget(event.target)) return;
    const direction = ({ ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" } as const)[event.key as "ArrowLeft"];
    if (!direction) return;
    event.preventDefault();
    move(direction);
  };

  const reviewLayout: Layout[] = blocks.map((block) => {
    const element = elements.find((candidate) => candidate.id === `review:${block.block_id}`);
    return { i: block.block_id, x: element?.x ?? block.x, y: element?.row ?? block.y, w: element?.w ?? block.w, h: element?.row_span ?? block.h, minW: 2, minH: 2 };
  });
  const commitReviewLayout = (_layout: Layout[], _oldItem: Layout, item: Layout) => {
    const id = `review:${item.i}`;
    onPresentationChange(updateElement(presentation, id, (element) => ({ ...element, x: item.x, row: item.y, w: item.w, row_span: item.h })));
  };

  const historySpan = Math.max(2, historicalElement?.row_span ?? 3);
  const footnoteSpan = Math.max(3, footnoteElement?.row_span ?? 4);
  const gapRows = Math.max(1, Math.ceil((footnoteElement?.gap_pt ?? 6) / LAYOUT_PT_STEP));
  const groupLayout: Layout[] = [
    { i: "historical_performance", x: historicalElement?.x ?? 0, y: 0, w: historicalElement?.w ?? GRID_COLUMNS, h: historySpan, minW: 4, minH: 2 },
    { i: "footnote:historical", x: historicalElement?.x ?? 0, y: historySpan + gapRows, w: historicalElement?.w ?? GRID_COLUMNS, h: footnoteSpan, minW: 4, minH: 3 },
  ];
  const commitGroupLayout = (_layout: Layout[], oldItem: Layout, item: Layout, resized: boolean) => {
    if (!historicalElement || !footnoteElement) return;
    const x = item.x;
    const w = item.w;
    let next = updateHistoricalGroup(presentation, (element) => ({ ...element, x, w }));
    if (item.i === "historical_performance") {
      const rowDelta = item.y - oldItem.y;
      const nextHistoryRow = historicalElement.row + rowDelta;
      const nextHistorySpan = resized ? item.h : historicalElement.row_span;
      next = updateElement(next, "historical_performance", (element) => ({
        ...element,
        row: nextHistoryRow,
        row_span: nextHistorySpan,
        offset_y_pt: clamp((element.offset_y_pt ?? 0) + rowDelta * LAYOUT_PT_STEP, MIN_OFFSET_Y_PT, MAX_OFFSET_Y_PT),
      }));
      next = updateElement(next, "footnote:historical", (element) => ({
        ...element,
        row: nextHistoryRow + nextHistorySpan + gapRows,
      }));
    } else {
      const gap = clamp((footnoteElement.gap_pt ?? 6) + (item.y - oldItem.y) * LAYOUT_PT_STEP, TYPOGRAPHY_LIMITS.spacing.min, TYPOGRAPHY_LIMITS.spacing.max);
      next = updateElement(next, "footnote:historical", (element) => ({
        ...element,
        row: historicalElement.row + historicalElement.row_span + Math.max(1, Math.ceil(gap / LAYOUT_PT_STEP)),
        row_span: resized ? item.h : element.row_span,
        gap_pt: gap,
      }));
    }
    setGroupDownRoomPt(null);
    onPresentationChange(next);
  };

  const selectedLabel = selectedElement ? elementLabel(selectedElement.id, blocks, historicalTitle, t("historicalFootnote")) : "";
  const interactive = !disabled && !expandedId;
  const expandedReviewBlock = expandedId?.startsWith("review:")
    ? blocks.find((block) => `review:${block.block_id}` === expandedId)
    : undefined;
  const expandedElement = expandedId ? elements.find((element) => element.id === expandedId) : undefined;
  let inspector: ReactNode = null;
  if (expandedReviewBlock && expandedElement) {
    inspector = <ReviewBlockEditor
      block={expandedReviewBlock}
      element={expandedElement}
      disabled={disabled}
      selected
      expanded
      onSelect={() => setSelectedId(expandedElement.id)}
      onExpand={closeInspector}
      onTitleChange={(title) => onBlocksChange(blocks.map((item) => item.block_id === expandedReviewBlock.block_id ? { ...item, title } : item))}
      onChange={(content) => onBlocksChange(blocks.map((item) => item.block_id === expandedReviewBlock.block_id ? { ...item, content } : item))}
      onElementChange={(change) => onPresentationChange(changeElementStyle(presentation, expandedElement.id, change))}
    />;
  } else if (expandedId === "historical_performance" && historicalElement) {
    inspector = <HistoricalEditor historicalTitle={historicalTitle} element={historicalElement} disabled={disabled} selected expanded onSelect={() => setSelectedId("historical_performance")} onExpand={closeInspector} onChange={(change) => onPresentationChange(changeElementStyle(presentation, "historical_performance", change))} />;
  } else if (expandedId === "footnote:historical" && footnoteElement) {
    inspector = <HistoricalFootnoteEditor element={footnoteElement} disabled={disabled} selected expanded onSelect={() => setSelectedId("footnote:historical")} onExpand={closeInspector} onChange={(change) => onPresentationChange(changeElementStyle(presentation, "footnote:historical", change))} onTextChange={onHistoricalFootnoteChange} />;
  }
  return <div ref={editorRoot} className={`page-one-editor${expandedId ? " inspector-open" : ""}`} tabIndex={0} onKeyDown={handleKeyDown}>
    {expandedId && <button type="button" className="module-inspector-backdrop" aria-label={t("closeInspector")} onClick={closeInspector} />}
    {inspector}
    <div className="review-pane-switch" role="group" aria-label={t("reviewPane")}><button aria-pressed={mobilePane === "edit"} onClick={() => setMobilePane("edit")}><Pencil size={16} /> {t("edit")}</button><button aria-pressed={mobilePane === "preview"} onClick={() => setMobilePane("preview")}><Eye size={16} /> {t("preview")}</button></div>
    <div aria-hidden={expandedId ? true : undefined} className={`page-one-editor-grid mobile-${mobilePane}${previewCollapsed ? " preview-collapsed" : ""}`}>
      <section className="page-one-edit-pane">
        <div className="layout-nudge-controls" aria-label={t("layoutControls")}>
          <span>{t("selectedModule")}: <strong>{selectedLabel}</strong></span>
          <div>
            <button type="button" className="icon-button" aria-label={t("moveLeft")} title={t("moveLeft")} aria-keyshortcuts="ArrowLeft" disabled={disabled || !canMoveHorizontal(-1)} onClick={() => move("left")}><ArrowLeft size={17} /></button>
            <button type="button" className="icon-button" aria-label={t("moveUp")} title={t("moveUp")} aria-keyshortcuts="ArrowUp" disabled={disabled || !canMoveVertical(-1)} onClick={() => move("up")}><ArrowUp size={17} /></button>
            <button type="button" className="icon-button" aria-label={t("moveDown")} title={t("moveDown")} aria-keyshortcuts="ArrowDown" disabled={disabled || !canMoveVertical(1)} onClick={() => move("down")}><ArrowDown size={17} /></button>
            <button type="button" className="icon-button" aria-label={t("moveRight")} title={t("moveRight")} aria-keyshortcuts="ArrowRight" disabled={disabled || !canMoveHorizontal(1)} onClick={() => move("right")}><ArrowRight size={17} /></button>
          </div>
          <small>{t("nudgeHelp")}</small>
        </div>
        <div className="review-builder">
          <div className="review-builder-tools"><span>{t("canvasHelp")}</span></div>
          <TwelveColumnGrid
            className="review-grid"
            layout={reviewLayout}
            cols={GRID_COLUMNS}
            rowHeight={GRID_ROW_HEIGHT}
            margin={[GRID_GAP, GRID_GAP]}
            containerPadding={[0, 0]}
            compactType={null}
            preventCollision
            isDraggable={interactive}
            isResizable={interactive}
            draggableHandle=".review-drag-handle"
            draggableCancel="button, input, textarea, select, a, [contenteditable='true']"
            onDragStart={(_layout, _old, item) => setSelectedId(`review:${item.i}`)}
            onDragStop={commitReviewLayout}
            onResizeStop={commitReviewLayout}
          >
            {blocks.map((block) => {
              const id = `review:${block.block_id}`;
              const element = elements.find((candidate) => candidate.id === id) ?? {
                id, row: block.y, row_span: block.h, x: block.x, w: block.w, vertical_nudge_steps: 0,
                title_style: REVIEW_TITLE_STYLE, body_style: REVIEW_BODY_STYLE,
              };
              return <div key={block.block_id} onFocus={() => setSelectedId(id)}>
                <ReviewBlockEditor
                  block={block}
                  element={element}
                  disabled={disabled}
                  selected={selectedId === id}
                  expanded={false}
                  onSelect={() => setSelectedId(id)}
                  onExpand={(trigger) => openInspector(id, trigger)}
                  onTitleChange={(title) => onBlocksChange(blocks.map((item) => item.block_id === block.block_id ? { ...item, title } : item))}
                  onChange={(content) => onBlocksChange(blocks.map((item) => item.block_id === block.block_id ? { ...item, content } : item))}
                  onElementChange={(change) => onPresentationChange(changeElementStyle(presentation, id, change))}
                />
              </div>;
            })}
          </TwelveColumnGrid>
        </div>

        <section className="review-page-controls" aria-label={t("reviewPageControls")}>
          <div><strong>{t("historyFootnotePage")}</strong><span>{t("pageOf", { page: historyPage, total: pageCount })}</span></div>
          <label><span>{t("pageNumber")}</span><input aria-label={t("pageNumber")} type="number" min={1} max={MAX_REVIEW_PAGES} value={historyPage} disabled={disabled} onChange={(event) => { const value = Number(event.target.value); if (Number.isInteger(value) && value >= 1 && value <= MAX_REVIEW_PAGES) moveHistoryGroupToPage(value); }} /></label>
          <button type="button" disabled={disabled || historyPage <= 1} onClick={() => moveHistoryGroupToPage(historyPage - 1)}><ArrowUp size={16} /> {t("previousPage")}</button>
          <button type="button" disabled={disabled || historyPage >= MAX_REVIEW_PAGES} onClick={() => moveHistoryGroupToPage(historyPage + 1, true)}><ArrowDown size={16} /> {t("nextPage")}</button>
          <button type="button" disabled={disabled || pageCount >= MAX_REVIEW_PAGES} onClick={() => onPresentationChange({ ...presentation, page_one: { ...presentation.page_one, review_page_count: pageCount + 1 } })}><Plus size={16} /> {t("addReviewPage")}</button>
        </section>

        {historicalElement && footnoteElement && <div className="historical-group-builder">
          <div className="review-builder-tools"><span>{t("openingPage", { page: historyPage })}</span><small>{t("historyGroupHelp")}</small></div>
          <TwelveColumnGrid
            className="review-grid historical-group-grid"
            layout={groupLayout}
            cols={GRID_COLUMNS}
            rowHeight={GRID_ROW_HEIGHT}
            margin={[GRID_GAP, GRID_GAP]}
            containerPadding={[0, 0]}
            compactType={null}
            preventCollision={false}
            allowOverlap
            isDraggable={interactive}
            isResizable={interactive}
            draggableHandle=".review-drag-handle"
            draggableCancel="button, input, textarea, select, a, [contenteditable='true']"
            onDragStart={(_layout, _old, item) => setSelectedId(item.i)}
            onDragStop={(layout, oldItem, item) => commitGroupLayout(layout, oldItem, item, false)}
            onResizeStop={(layout, oldItem, item) => commitGroupLayout(layout, oldItem, item, true)}
          >
            <div key="historical_performance">
              <HistoricalEditor historicalTitle={historicalTitle} element={historicalElement} disabled={disabled} selected={selectedId === "historical_performance"} expanded={false} onSelect={() => setSelectedId("historical_performance")} onExpand={(trigger) => openInspector("historical_performance", trigger)} onChange={(change) => onPresentationChange(changeElementStyle(presentation, "historical_performance", change))} />
            </div>
            <div key="footnote:historical">
              <HistoricalFootnoteEditor element={footnoteElement} disabled={disabled} selected={selectedId === "footnote:historical"} expanded={false} onSelect={() => setSelectedId("footnote:historical")} onExpand={(trigger) => openInspector("footnote:historical", trigger)} onChange={(change) => onPresentationChange(changeElementStyle(presentation, "footnote:historical", change))} onTextChange={onHistoricalFootnoteChange} />
            </div>
          </TwelveColumnGrid>
        </div>}
      </section>
      <PreviewPane html={previewHtml} busy={previewBusy} error={previewError} collapsed={previewCollapsed} onToggle={() => setPreviewCollapsed((value) => !value)} selectedId={selectedId} onSelect={(id) => { setSelectedId(id); setMobilePane("edit"); }} onArrow={move} onGroupDownRoomChange={setGroupDownRoomPt} />
    </div>
  </div>;
}
