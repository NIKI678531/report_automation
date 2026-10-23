import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Calculator, Database, Pencil, RefreshCw, RotateCcw, Save, Sparkles } from "lucide-react";
import { api, type DatasetSlot, type Report } from "../api";
import { SectorDonut, sectorSlices, type SectorChartSnapshot } from "../features/analytics/SectorDonut";
import { CompanyNewsWorkbench } from "../features/news/CompanyNewsWorkbench";
import { legacyReviewBlocks, pageOnePresentation, retargetHistoricalFootnoteStyles, richHtmlToPlainText, ReviewCanvas, type PageOnePresentation, type ReviewBlock } from "../features/review/ReviewCanvas";
import { FOOTNOTE_SECTIONS, isReportReadOnly, reportConstituentsTitle, reportMonthName, reportProductTicker, reportTitle, reportTitleOverrides, reviewLegacyText, type FootnoteSectionKey, type ModuleId } from "../reportModules";
import type { RegisterPendingSave } from "../pendingSave";
import { CsvDatasetUpload } from "./CsvDatasetUpload";
import { MarkerInput, MarkerTextarea } from "./SuperscriptMarkerControl";
import { reportLocale, useLocale } from "../i18n";

type RunAction = (work: () => Promise<unknown>) => Promise<void>;
type JsonRecord = Record<string, unknown>;
const IGNORE_PENDING_SAVE: RegisterPendingSave = () => undefined;

interface ModuleProps { report: Report; active: ModuleId; busy: boolean; run: RunAction; registerPendingSave?: RegisterPendingSave; }

function sectionsOf(report: Report): JsonRecord {
  return (report.latest_document?.content.sections as JsonRecord | undefined) ?? {};
}

function rows(value: unknown): JsonRecord[] { return Array.isArray(value) ? value as JsonRecord[] : []; }
function percent(value: unknown, locale = "en-HK", missing = "N/A"): string {
  const numeric = typeof value === "number" || typeof value === "string" ? Number(value) : Number.NaN;
  return Number.isFinite(numeric) ? new Intl.NumberFormat(locale, { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(numeric) : missing;
}
/** A missing close price is not a price of zero, and the review gate cannot catch what looks real. */
function price(value: unknown, missing = "N/A"): string {
  const numeric = typeof value === "number" || typeof value === "string" ? Number(value) : Number.NaN;
  return Number.isFinite(numeric) ? numeric.toFixed(2) : missing;
}
function performanceValue(value: unknown, missing = "N/A"): string {
  const numeric = typeof value === "number" || typeof value === "string" ? Number(value) : Number.NaN;
  return Number.isFinite(numeric) ? (numeric * 100).toFixed(2) : missing;
}

function portfolioDisplayValue(row: JsonRecord): string {
  const value = row.display_value ?? row.value;
  if (typeof value === "number") return String(value);
  if (typeof value === "string" && value.trim()) return value;
  return "N/A";
}

function portfolioRows(value: unknown): JsonRecord[] {
  const source = rows(value);
  const currency = source
    .map((row) => typeof row.currency === "string" ? row.currency.trim().toUpperCase() : "")
    .find(Boolean) || "HKD";
  const codeOf = (row: JsonRecord): string => {
    const code = String(row.metric_code ?? "").trim().toUpperCase();
    if (code) return code;
    const label = String(row.label ?? "").trim().toLowerCase();
    if (label.startsWith("asset under management")) return "AUM";
    if (label.startsWith("average daily turnover")) return "AVERAGE_DAILY_TURNOVER";
    if (label === "number of holdings") return "NUMBER_OF_HOLDINGS";
    return "";
  };
  const specifications = [
    { metric_code: "AUM", label: `Asset Under Management (${currency})^`, unit: "million", display_precision: 2 },
    { metric_code: "AVERAGE_DAILY_TURNOVER", label: `Average Daily Turnover (${currency})^^`, unit: "million", display_precision: 0 },
    { metric_code: "NUMBER_OF_HOLDINGS", label: "Number of holdings", unit: "count", display_precision: 0 },
  ];
  return specifications.map((fallback) => {
    const existing = source.find((row) => codeOf(row) === fallback.metric_code);
    const displayValue = existing ? portfolioDisplayValue({
      display_value: existing.display_value,
      value: existing.value,
    }) : "N/A";
    return {
      raw_value: null,
      ...(fallback.metric_code === "NUMBER_OF_HOLDINGS" ? {} : { currency }),
      ...fallback,
      ...existing,
      metric_code: fallback.metric_code,
      label: fallback.label,
      display_value: displayValue,
      value: displayValue,
      ...(displayValue === "N/A" ? { availability: "MISSING_SOURCE_DATA" } : {}),
    };
  });
}

function ModuleHeading({ eyebrow, title, description, actions }: { eyebrow: string; title: ReactNode; description: string; actions?: ReactNode }) {
  return <header className="module-heading"><div><span className="eyebrow">{eyebrow}</span><h2>{title}</h2><p>{description}</p></div>{actions && <div className="module-actions">{actions}</div>}</header>;
}

function reviewTitleOf(report: Report, review: JsonRecord): string {
  const monthDate = new Date(`${report.report_date.slice(0, 7)}-01T00:00:00Z`);
  const defaults = {
    EN: `${new Intl.DateTimeFormat("en", { month: "long", timeZone: "UTC" }).format(monthDate)} in Review`,
    ZH_HANS: `${Number(report.report_date.slice(5, 7))}月月度回顾`,
    ZH_HANT: `${Number(report.report_date.slice(5, 7))}月月度回顧`,
  };
  const localizedDefault = defaults[report.language_mode === "BILINGUAL" ? "EN" : report.language_mode];
  for (const value of [review.display_title, review.title]) {
    if (typeof value === "string" && value.trim()) return !isReportReadOnly(report) && [...Object.values(defaults), "Monthly Review", "Monthly summary", "月度回顾", "月度回顧"].includes(value.trim()) ? localizedDefault : value.trim();
  }
  return localizedDefault;
}

export function ReportModule({ report, active, busy, run, registerPendingSave = IGNORE_PENDING_SAVE }: ModuleProps) {
  if (active === "review") return <ReviewModule report={report} busy={busy} run={run} registerPendingSave={registerPendingSave} />;
  if (active === "performance") return <PerformanceModule report={report} busy={busy} run={run} registerPendingSave={registerPendingSave} />;
  if (active === "news") return <NewsModule report={report} busy={busy} run={run} registerPendingSave={registerPendingSave} />;
  if (active === "constituents") return <ConstituentsModule report={report} busy={busy} run={run} registerPendingSave={registerPendingSave} />;
  if (active === "analytics") return <AnalyticsModule report={report} busy={busy} run={run} registerPendingSave={registerPendingSave} />;
  if (active === "footnotes") return <FootnotesModule report={report} busy={busy} run={run} registerPendingSave={registerPendingSave} />;
  return null;
}

function ReportTitleField({ label, value, overridden, disabled, onChange, onReset }: {
  label: string;
  value: string;
  overridden: boolean;
  disabled: boolean;
  onChange: (value: string) => void;
  onReset: () => void;
}) {
  const { t } = useLocale();
  const id = useId();
  return <div className="report-title-field">
    <div className="report-title-label">
      <label htmlFor={id}>{label}</label>
      <button type="button" className="icon-button" disabled={disabled || !overridden}
        title={t("resetReportTitle", { title: label })} aria-label={t("resetReportTitle", { title: label })}
        onClick={onReset}><RotateCcw size={16} /></button>
    </div>
    <MarkerInput id={id} value={value} maxLength={200} required disabled={disabled} onValueChange={onChange} />
  </div>;
}

function ReportTitleFields({ defaults, overrides, disabled, onChange, productName, terminology, onTerminologyChange }: {
  defaults: Record<string, string>;
  overrides: Record<string, string>;
  disabled: boolean;
  onChange: (value: Record<string, string>) => void;
  productName: string;
  terminology: JsonRecord;
  onTerminologyChange: (value: JsonRecord) => void;
}) {
  const { t } = useLocale();
  const groups = [
    { label: "historicalPerformance", keys: ["historical_performance"] },
    { label: "companyNews", keys: ["company_news"] },
    { label: "constituentPerformance", keys: ["constituent_performance"] },
    { label: "finalAnalytics", keys: ["top10", "sector_breakdown", "performers", "top_performers", "bottom_performers", "portfolio_analysis", "portfolio.AUM", "portfolio.AVERAGE_DAILY_TURNOVER", "portfolio.NUMBER_OF_HOLDINGS"] },
  ] as const;
  const storedProductName = terminology.product_name;
  const productNameOverride = typeof storedProductName === "string" && storedProductName !== ""
    ? storedProductName
    : undefined;
  return <section className="report-title-editor" aria-label={t("reportTitles")}>
    <details>
      <summary>{t("reportTitles")}</summary>
      <ReportTitleField label={t("productName")} value={productNameOverride ?? productName}
        overridden={productNameOverride !== undefined} disabled={disabled}
        onChange={(value) => onTerminologyChange({ ...terminology, product_name: value })}
        onReset={() => { const next = { ...terminology }; delete next.product_name; onTerminologyChange(next); }} />
      {groups.map((group) => <section className="report-title-group" key={group.label}>
        <h4>{t(group.label)}</h4>
        {group.keys.filter((key) => defaults[key] !== undefined).map((key) => <ReportTitleField
          key={key} label={defaults[key]} value={overrides[key] ?? defaults[key]}
          overridden={overrides[key] !== undefined} disabled={disabled}
          onChange={(value) => onChange({ ...overrides, [key]: value })}
          onReset={() => { const next = { ...overrides }; delete next[key]; onChange(next); }}
        />)}
      </section>)}
    </details>
  </section>;
}

function ReviewModule({ report, busy, run, registerPendingSave = IGNORE_PENDING_SAVE }: Omit<ModuleProps, "active">) {
  const { t } = useLocale();
  const locale = reportLocale(report.language_mode);
  const version = report.latest_document?.version ?? 1;
  const content = report.latest_document?.content as JsonRecord | undefined;
  const review = (sectionsOf(report).month_in_review as JsonRecord | undefined) ?? {};
  const defaultReviewTitle = reviewTitleOf(report, review);
  const initialTerminology = useMemo(() => (content?.terminology_overrides as JsonRecord | undefined) ?? {}, [report.id, version]);
  const initialTitleOverrides = useMemo(() => reportTitleOverrides(content), [report.id, version]);
  const initialBlocks = useMemo(() => legacyReviewBlocks(review, defaultReviewTitle, report.language_mode ?? "EN", !isReportReadOnly(report)), [report.id, version]);
  const initialHistoricalFootnote = useMemo(() => String(((sectionsOf(report).footnotes as JsonRecord | undefined) ?? {}).historical ?? ""), [report.id, version]);
  const initialPresentation = useMemo(() => pageOnePresentation(content?.presentation, initialBlocks, initialHistoricalFootnote), [report.id, version, initialBlocks, initialHistoricalFootnote]);
  const [blocks, setBlocks] = useState<ReviewBlock[]>(initialBlocks);
  const [presentation, setPresentation] = useState<PageOnePresentation>(initialPresentation);
  const [historicalFootnote, setHistoricalFootnote] = useState(initialHistoricalFootnote);
  const [terminology, setTerminology] = useState<JsonRecord>(initialTerminology);
  const [titleOverrides, setTitleOverrides] = useState(initialTitleOverrides);
  const [previewHtml, setPreviewHtml] = useState("");
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const previewSequence = useRef(0);
  useEffect(() => {
    setBlocks(initialBlocks);
    setPresentation(initialPresentation);
    setHistoricalFootnote(initialHistoricalFootnote);
    setTerminology((content?.terminology_overrides as JsonRecord | undefined) ?? {});
    setTitleOverrides(initialTitleOverrides);
  }, [report.id, version, initialBlocks, initialHistoricalFootnote, initialPresentation, initialTitleOverrides]);
  const draftContent = useMemo(() => {
    const next = structuredClone(content ?? {}) as JsonRecord;
    const nextSections = (next.sections as JsonRecord | undefined) ?? {};
    next.sections = nextSections;
    const section = (nextSections.month_in_review as JsonRecord | undefined) ?? {};
    nextSections.month_in_review = section;
    const summaryBlock = blocks.find((block) => block.block_id === "summary") ?? blocks.find((block) => block.type === "rich_text");
    const normalizedTitle = summaryBlock?.title.trim() || defaultReviewTitle;
    section.title = normalizedTitle;
    section.display_title = normalizedTitle;
    section.layout_schema_version = 3;
    section.blocks = blocks.map((block) => {
      const element = presentation.page_one.elements.find((candidate) => candidate.id === `review:${block.block_id}`);
      return element ? { ...block, x: element.x, y: element.row, w: element.w, h: element.row_span } : block;
    });
    const legacyText = reviewLegacyText(blocks);
    section.summary = legacyText.summary;
    section.outlook = legacyText.outlook;
    const footnotes = (nextSections.footnotes as JsonRecord | undefined) ?? {};
    const historicalRichText = presentation.page_one.elements.find((element) => element.id === "footnote:historical")?.content_html;
    const synchronizedHistoricalFootnote = typeof historicalRichText === "string" ? richHtmlToPlainText(historicalRichText) : historicalFootnote;
    nextSections.footnotes = { ...footnotes, historical: synchronizedHistoricalFootnote };
    next.presentation = presentation;
    next.terminology_overrides = terminology;
    if (content?.title_overrides !== undefined || Object.keys(titleOverrides).length) next.title_overrides = titleOverrides;
    return next;
  }, [blocks, content, defaultReviewTitle, historicalFootnote, presentation, terminology, titleOverrides]);
  const persist = useCallback(async () => { await api.saveDocument(report.id, version, draftContent); }, [draftContent, report.id, version]);
  const frozen = isReportReadOnly(report);
  useEffect(() => {
    if (!report.latest_document) return undefined;
    const controller = new AbortController();
    const sequence = ++previewSequence.current;
    setPreviewBusy(true);
    setPreviewError("");
    const timer = window.setTimeout(() => {
      (frozen
        ? api.previewSaved(report.id, controller.signal)
        : api.previewDraft(report.id, version, draftContent, controller.signal))
        .then((html) => { if (sequence === previewSequence.current) setPreviewHtml(html); })
        .catch((caught: unknown) => {
          if (controller.signal.aborted || sequence !== previewSequence.current) return;
          setPreviewError(String(caught));
        })
        .finally(() => { if (sequence === previewSequence.current) setPreviewBusy(false); });
    }, 300);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [draftContent, frozen, report.id, report.latest_document, version]);
  const dirty = !frozen && (
    JSON.stringify(blocks) !== JSON.stringify(initialBlocks)
    || JSON.stringify(presentation) !== JSON.stringify(initialPresentation)
    || historicalFootnote !== initialHistoricalFootnote
    || JSON.stringify(terminology) !== JSON.stringify(initialTerminology)
    || JSON.stringify(titleOverrides) !== JSON.stringify(initialTitleOverrides)
  );
  useLayoutEffect(() => {
    registerPendingSave(dirty ? persist : null);
    return () => registerPendingSave(null);
  }, [dirty, persist, registerPendingSave]);
  const setNamedTerm = (field: "securities" | "industries", key: string, value: string) => setTerminology((current) => ({ ...current, [field]: { ...((current[field] as JsonRecord | undefined) ?? {}), [key]: value } }));
  const constituentNames = rows(sectionsOf(report).constituents);
  const industryNames = rows((((sectionsOf(report).analytics as JsonRecord | undefined)?.sector_chart as JsonRecord | undefined)?.series));
  const assistedPrompt = locale === "zh-Hans" ? "请在审核人确认后完成展望。" : locale === "zh-Hant" ? "請在審閱人確認後完成展望。" : "Complete the outlook after reviewer confirmation.";
  const localizedConstituentName = (row: JsonRecord) => locale === "zh-Hans" ? row.name_zh_hans : row.name_zh_hant;
  const localizedIndustryName = (row: JsonRecord) => locale === "zh-Hans" ? row.label_zh_hans : row.label_zh_hant;
  return <><ModuleHeading eyebrow={t("pageDetail", { page: "01", detail: t("freeLayout") })} title={t("monthReview")} description={t("reviewDescription")} actions={<><button disabled={busy || !report.active_snapshot_id || frozen} onClick={() => run(() => api.generateDraft(report.id, version, assistedPrompt))}><Sparkles size={16} /> {t("assistedDraft")}</button><button className="primary" disabled={busy || frozen || !dirty} onClick={() => run(persist)}><Save size={16} /> {t("saveLayout")}</button></>} />{locale !== "en" && <section className="terminology-review"><h3>{t("terminologyReview")}</h3><p>{t("terminologyHelp")}</p>{constituentNames.length > 0 && <details><summary>{t("securityNames")}</summary><div className="terminology-list">{constituentNames.map((row) => { const key = String(row.security_code ?? row.ticker ?? ""); const stored = (terminology.securities as JsonRecord | undefined) ?? {}; return <label key={key}><span>{row.ticker ? String(row.ticker) : key}</span><input value={String(stored[key] ?? localizedConstituentName(row) ?? "")} disabled={frozen} onChange={(event) => setNamedTerm("securities", key, event.target.value)} /></label>; })}</div></details>}{industryNames.length > 0 && <details><summary>{t("industryNames")}</summary><div className="terminology-list">{industryNames.map((row) => { const key = String(row.code ?? ""); const stored = (terminology.industries as JsonRecord | undefined) ?? {}; return <label key={key}><span>{key}</span><input value={String(stored[key] ?? localizedIndustryName(row) ?? "")} disabled={frozen} onChange={(event) => setNamedTerm("industries", key, event.target.value)} /></label>; })}</div></details>}</section>}
    <ReportTitleFields defaults={report.report_title_defaults ?? {}} overrides={titleOverrides} disabled={frozen || busy}
      onChange={setTitleOverrides} productName={report.product_name} terminology={terminology} onTerminologyChange={setTerminology} />
    <ReviewCanvas blocks={blocks} presentation={presentation} historicalFootnote={historicalFootnote}
      historicalTitle={titleOverrides.historical_performance ?? report.report_title_defaults?.historical_performance ?? t("historicalTitle")}
      disabled={frozen || busy} previewHtml={previewHtml} previewBusy={previewBusy} previewError={previewError}
      onBlocksChange={setBlocks} onPresentationChange={setPresentation} onHistoricalFootnoteChange={(value) => {
        setHistoricalFootnote(value);
        setPresentation((current) => retargetHistoricalFootnoteStyles(current, value));
      }} /></>;
}

function PerformanceModule({ report, busy, run }: Omit<ModuleProps, "active">) {
  const { locale, t } = useLocale();
  const performance = (sectionsOf(report).historical_performance as JsonRecord | undefined) ?? {};
  const data = rows(performance.rows);
  const displayRows = [
    { role: "FUND", label: "3033.HK" },
    { role: "BENCHMARK", label: "HSTECHN Index" },
  ];
  return <>
    <ModuleHeading eyebrow={t("pageDetail", { page: "02", detail: t("cdbAutomatic") })} title={t("historicalPerformance")} description={t("performanceDescription", { benchmark: report.benchmark_instrument_code })} actions={<button disabled={busy || isReportReadOnly(report)} onClick={() => run(() => api.refreshAutomaticData(report.id, report.version))}><RefreshCw size={16} /> {t("refreshWarehouse")}</button>} />
    <section className="data-surface">
      <h3>{reportTitle(report, "historical_performance", t("historicalTitle"))}</h3>
      <table>
        <thead><tr><th aria-label={t("instrument")}></th><th>{t("return1m")}</th><th>{t("return3m")}</th><th>{t("return6m")}</th><th>{t("returnYtd")}</th></tr></thead>
        <tbody>{displayRows.map(({ role, label }, index) => {
          const row = data.find((candidate) => candidate.role === role) ?? data[index] ?? {};
          return <tr key={role}><th scope="row">{label}</th><td>{performanceValue(row.return_1m, t("noData"))}</td><td>{performanceValue(row.return_3m, t("noData"))}</td><td>{performanceValue(row.return_6m, t("noData"))}</td><td>{performanceValue(row.return_ytd, t("noData"))}</td></tr>;
        })}</tbody>
      </table>
      {!data.length && <EmptyData />}
    </section>
    <FormulaStrip title={t("officialReturns")} formula="CDB returns_l1m · returns_l3m · returns_l6m · returns_ytd" detail={t("formulaReturnDetail")} />
  </>;
}

function NewsModule({ report, busy, run, registerPendingSave = IGNORE_PENDING_SAVE }: Omit<ModuleProps, "active">) {
  const { t } = useLocale();
  return <><ModuleHeading eyebrow={t("pageDetail", { page: "03", detail: t("daCatalog") })} title={reportTitle(report, "company_news", t("companyNews"))} description={t("newsDescription")} /><CompanyNewsWorkbench key={report.id} report={report} busy={busy} run={run} selectedSnapshot={rows(sectionsOf(report).company_news)} registerPendingSave={registerPendingSave} /></>;
}

function ConstituentsModule({ report, busy, run, registerPendingSave = IGNORE_PENDING_SAVE }: Omit<ModuleProps, "active">) {
  const { locale, t, formatDate } = useLocale();
  const version = report.latest_document?.version ?? 1;
  const content = report.latest_document?.content as JsonRecord | undefined;
  const initialDate = useMemo(() => typeof content?.next_rebalancing_date === "string" ? content.next_rebalancing_date : "", [report.id, version]);
  const [rebalancingDate, setRebalancingDate] = useState(initialDate);
  useEffect(() => setRebalancingDate(typeof content?.next_rebalancing_date === "string" ? content.next_rebalancing_date : ""), [report.id, version]);
  const persist = useCallback(async () => {
    const next = structuredClone(content ?? {}) as JsonRecord;
    next.next_rebalancing_date = rebalancingDate;
    next.next_rebalancing_date_source = "MANUAL";
    await api.saveDocument(report.id, version, next);
  }, [content, rebalancingDate, report.id, version]);
  const frozen = isReportReadOnly(report);
  const dirty = !frozen && rebalancingDate !== initialDate;
  useLayoutEffect(() => {
    registerPendingSave(dirty && rebalancingDate ? persist : null);
    return () => registerPendingSave(null);
  }, [dirty, persist, rebalancingDate, registerPendingSave]);
  const data = rows(sectionsOf(report).constituents);
  const productTicker = reportProductTicker(report);
  const dateLocale = locale === "zh-Hans" ? "zh-CN" : locale === "zh-Hant" ? "zh-HK" : "en-HK";
  const localizedConstituent = (row: JsonRecord) => locale === "zh-Hans" ? row.name_zh_hans : locale === "zh-Hant" ? row.name_zh_hant : row.name_en;
  const localizedIndustry = (row: JsonRecord) => locale === "zh-Hans" ? row.effective_industry_name_zh_hans : locale === "zh-Hant" ? row.effective_industry_name_zh_hant : row.sector;
  const constituentTitle = reportTitle(report, "constituent_performance", locale === "en" ? reportConstituentsTitle(report) : t("constituentsTitle", { product: productTicker }));
  return <><ModuleHeading eyebrow={t("pageDetail", { page: "04", detail: t("cdbFmp") })} title={constituentTitle} description={data.length ? t("holdingsBound", { count: data.length, month: report.report_date.slice(0, 7) }) : t("holdingsEmpty")} actions={<button className="primary" disabled={busy || frozen || !dirty || !rebalancingDate} onClick={() => run(persist)}><Save size={16} /> {t("saveDate")}</button>} />
    <section className="rebalancing-editor" aria-label={t("rebalancingEditor")}><label><span>{t("nextRebalancingDate")}</span><input aria-label={locale === "en" ? "Next rebalancing date" : t("nextRebalancingDate")} type="date" value={rebalancingDate} disabled={frozen} onChange={(event) => setRebalancingDate(event.target.value)} /></label><p>{locale !== "en" ? `(*${t("nextRebalancingDate")}：${rebalancingDate ? formatDate(rebalancingDate) : t("noData")})` : `(*Next Rebalancing Date: ${rebalancingDate ? formatDate(rebalancingDate) : t("noData")})`}</p></section>
    <ConstituentSources report={report} busy={busy} run={run} /><section className="data-surface constituent-table"><table><thead><tr><th>{t("code")}</th><th>{t("constituent")}</th><th>{t("price")}</th><th>{t("weightShort")}</th><th>1M</th><th>3M</th><th>6M</th><th>YTD</th></tr></thead><tbody>{data.map((row) => <tr key={String(row.security_code)}><th scope="row"><span className="security-code">{String(row.ticker ?? row.security_code)}</span></th><td><strong>{String(localizedConstituent(row) ?? "")}</strong><small>{String(localizedIndustry(row) ?? "")}</small></td><td>{row.close_price == null ? t("noData") : `${String(row.currency ?? "")} ${price(row.close_price, t("noData"))}`}</td><td>{percent(row.weight, dateLocale, t("noData"))}</td><td>{percent(row.return_1m, dateLocale, t("noData"))}</td><td>{percent(row.return_3m, dateLocale, t("noData"))}</td><td>{percent(row.return_6m, dateLocale, t("noData"))}</td><td>{percent(row.return_ytd, dateLocale, t("noData"))}</td></tr>)}</tbody></table>{!data.length && <EmptyData />}</section></>;
}

function ConstituentSources({ report, busy, run }: Omit<ModuleProps, "active">) {
  const { t, statusLabel } = useLocale();
  const [slots, setSlots] = useState<DatasetSlot[]>([]);
  useEffect(() => {
    api.listDatasets(report.id).then(setSlots).catch(() => setSlots([]));
  }, [report.id, report.active_snapshot_id, report.version]);
  const identity = slots.find((item) => item.key === "index_constituents");
  const returns = slots.find((item) => item.key === "constituent_returns");
  const fmpActive = returns?.state === "APPLIED" && returns.source_type === "FMP_API";
  const automaticState = fmpActive ? "APPLIED" : returns?.state === "APPLIED" ? "OVERRIDDEN" : "AVAILABLE";
  return <div className="constituent-source-grid">
    <article className="constituent-source-card">
      <span className="source-step">01 · {t("csvOverride")}</span>
      <CsvDatasetUpload report={report} datasetType="index_constituents" busy={busy} run={run} allowClear />
    </article>
    <article className="constituent-source-card" aria-label={t("automaticReturns")}>
      <div className="dataset-slot-head">
        <div><span className="source-step">02 · {t("automatic")}</span><strong>{t("automaticSourceTitle")}</strong><span>{t("automaticSourceHelp")}</span></div>
        <span className={`dataset-state state-${automaticState === "OVERRIDDEN" ? "available" : automaticState.toLowerCase()}`}>{statusLabel(automaticState)}</span>
      </div>
      <p className="dataset-current">{fmpActive ? t("returnRows", { returns: returns?.rows ?? 0, identities: identity?.rows ?? 0 }) : returns?.state === "APPLIED" ? t("currentReturnSource", { source: returns.source_name ?? returns.source_type ?? t("approvedOverride") }) : t("readyFor", { month: report.report_date.slice(0, 7) })}</p>
      <div className="dataset-actions"><button className="primary" disabled={busy || isReportReadOnly(report)} onClick={() => run(() => api.refreshAutomaticData(report.id, report.version))}><RefreshCw size={16} /> {t("loadAutomatically")}</button></div>
    </article>
  </div>;
}

function AnalyticsModule({ report, busy, run, registerPendingSave = IGNORE_PENDING_SAVE }: Omit<ModuleProps, "active">) {
  const { locale, t } = useLocale();
  const analytics = (sectionsOf(report).analytics as JsonRecord | undefined) ?? {};
  const top10 = rows(analytics.top10); const top = rows(analytics.top); const bottom = rows(analytics.bottom); const portfolio = portfolioRows(analytics.portfolio);
  const version = report.latest_document?.version ?? 1;
  const content = report.latest_document?.content;
  const initialTitleOverrides = useMemo(() => reportTitleOverrides(content), [report.id, version]);
  const turnoverValue = portfolioDisplayValue(portfolio.find((row) => row.metric_code === "AVERAGE_DAILY_TURNOVER") ?? {});
  const initialTurnover = turnoverValue === "N/A" ? "NA" : turnoverValue;
  const [turnover, setTurnover] = useState(initialTurnover);
  const [titleOverrides, setTitleOverrides] = useState(initialTitleOverrides);
  useEffect(() => {
    setTurnover(initialTurnover);
    setTitleOverrides(initialTitleOverrides);
  }, [report.id, version, initialTitleOverrides, initialTurnover]);
  const turnoverEnabled = report.product_code === "3033";
  const frozen = isReportReadOnly(report) || !content;
  const normalizedTurnover = turnover.trim() && turnover.trim() !== "N/A" ? turnover.trim() : "NA";
  const turnoverDirty = turnoverEnabled && normalizedTurnover !== initialTurnover.trim();
  const titleDirty = JSON.stringify(titleOverrides) !== JSON.stringify(initialTitleOverrides);
  const titlesValid = Object.values(titleOverrides).every((value) => value.trim().length >= 1 && value.trim().length <= 200);
  const dirty = !frozen && (turnoverDirty || titleDirty);
  const persist = useCallback(async () => {
    const next = structuredClone(content ?? {}) as JsonRecord;
    if (content?.title_overrides !== undefined || Object.keys(titleOverrides).length) next.title_overrides = titleOverrides;
    if (turnoverDirty) {
      const nextSections = (next.sections as JsonRecord | undefined) ?? {};
      next.sections = nextSections;
      const nextAnalytics = (nextSections.analytics as JsonRecord | undefined) ?? {};
      nextSections.analytics = nextAnalytics;
      const nextPortfolio = rows(nextAnalytics.portfolio);
      nextAnalytics.portfolio = nextPortfolio;
      const turnoverIndex = nextPortfolio.findIndex((row) => {
        const code = String(row.metric_code ?? "").trim().toUpperCase();
        return code ? code === "AVERAGE_DAILY_TURNOVER" : String(row.label ?? "").trim().toLowerCase().startsWith("average daily turnover");
      });
      const nextTurnover = {
        ...(turnoverIndex >= 0 ? nextPortfolio[turnoverIndex] : portfolioRows(nextPortfolio).find((row) => row.metric_code === "AVERAGE_DAILY_TURNOVER")),
        display_value: normalizedTurnover,
        value: normalizedTurnover,
      };
      if (turnoverIndex >= 0) nextPortfolio[turnoverIndex] = nextTurnover;
      else nextPortfolio.push(nextTurnover);
    }
    await api.saveDocument(report.id, version, next);
  }, [content, normalizedTurnover, report.id, titleOverrides, turnoverDirty, version]);
  useLayoutEffect(() => {
    registerPendingSave(dirty ? persist : null);
    return () => registerPendingSave(null);
  }, [dirty, persist, registerPendingSave]);
  const sectorChart = analytics.sector_chart as SectorChartSnapshot | undefined;
  const sectorSeries = sectorSlices(sectorChart, locale);
  const monthName = reportMonthName(report);
  const productTicker = reportProductTicker(report);
  const shownName = (row: JsonRecord) => String(locale === "zh-Hans" ? (row.issuer_zh_hans ?? "") : locale === "zh-Hant" ? (row.issuer_zh_hant ?? "") : (row.issuer ?? ""));
  const displayPortfolio: JsonRecord[] = portfolio.map((row): JsonRecord => {
    const displayValue = portfolioDisplayValue(row);
    return {
      ...row,
      label: titleOverrides[`portfolio.${row.metric_code}`] ?? reportTitle(report, `portfolio.${row.metric_code}`, String(locale === "zh-Hans" ? ({ AUM: "资产管理规模（百万港元）^", AVERAGE_DAILY_TURNOVER: "平均每日成交额（百万港元）^^", NUMBER_OF_HOLDINGS: "持仓数量" } as Record<string, string>)[String(row.metric_code)] ?? row.label : locale === "zh-Hant" ? ({ AUM: "資產管理規模（百萬港元）^", AVERAGE_DAILY_TURNOVER: "平均每日成交額（百萬港元）^^", NUMBER_OF_HOLDINGS: "持倉數量" } as Record<string, string>)[String(row.metric_code)] ?? row.label : row.label)),
      display_value: locale !== "en" && displayValue.endsWith(" million") ? displayValue.slice(0, -8) : displayValue,
    };
  });
  const numberLocale = locale === "zh-Hans" ? "zh-CN" : locale === "zh-Hant" ? "zh-HK" : "en-HK";
  const defaultTitle = (key: string, fallback: string) => report.report_title_defaults?.[key] ?? fallback;
  const title = (key: string, fallback: string) => titleOverrides[key] ?? defaultTitle(key, fallback);
  const setTitle = (key: string, value: string) => setTitleOverrides((current) => ({ ...current, [key]: value }));
  const resetTitle = (key: string) => setTitleOverrides((current) => { const next = { ...current }; delete next[key]; return next; });
  const top10Default = defaultTitle("top10", t("top10", { product: productTicker }));
  const sectorDefault = defaultTitle("sector_breakdown", t("sectorBreakdown", { product: productTicker }));
  const performersDefault = defaultTitle("performers", `${t("performersIn", { month: monthName })}**`);
  const portfolioDefault = defaultTitle("portfolio_analysis", t("portfolioAnalysis", { product: productTicker }));
  const top10Title = title("top10", top10Default);
  const sectorTitle = title("sector_breakdown", sectorDefault);
  const performersTitle = title("performers", performersDefault);
  const portfolioTitle = title("portfolio_analysis", portfolioDefault);
  const editableTitle = (index: string, key: string, value: string, fallback: string) => <EditableSectionTitle
    index={index} value={value} defaultValue={fallback} overridden={titleOverrides[key] !== undefined}
    disabled={busy || frozen} onChange={(next) => setTitle(key, next)} onReset={() => resetTitle(key)}
  />;
  const editableLabel = (key: string, fallback: string, label: string, editLabel: string, heading: "h4" | "span") => <EditableSectionTitle
    value={title(key, fallback)} defaultValue={defaultTitle(key, fallback)} overridden={titleOverrides[key] !== undefined}
    disabled={busy || frozen} onChange={(next) => setTitle(key, next)} onReset={() => resetTitle(key)}
    label={label} editLabel={editLabel} heading={heading}
  />;
  return <><ModuleHeading eyebrow={t("pageDetail", { page: "05", detail: t("calculatedOutputs") })} title={t("finalAnalytics")} description={t("analyticsDescription")} actions={<><button disabled={busy || frozen || !dirty || !titlesValid} onClick={() => run(persist)}><Save size={16} /> {t("saveAnalyticsTitles")}</button><button className="primary" disabled={busy || isReportReadOnly(report) || !report.active_snapshot_id || titleDirty} onClick={() => run(() => api.calculate(report.id))}><RefreshCw size={16} /> {t("refreshAnalytics")}</button></>} /><IndustryMasterStatus report={report} /><div className="analytics-grid"><section className="analytics-section">{editableTitle("01", "top10", top10Title, top10Default)}<table><tbody>{top10.map((row, index) => <tr key={`${String(row.issuer)}-${index}`}><th>{shownName(row)}</th><td>{percent(row.weight, numberLocale, t("noData"))}</td></tr>)}</tbody></table>{!top10.length && <EmptyData />}</section><section className="analytics-section">{editableTitle("02", "sector_breakdown", sectorTitle, sectorDefault)}{sectorSeries.length ? <SectorDonut chart={sectorChart} title={sectorTitle} /> : <EmptyData />}</section><section className="analytics-section">{editableTitle("03", "performers", performersTitle, performersDefault)}<div className="performer-columns">{(["top", "bottom"] as const).map((side) => <PerformerList key={side} title={title(`${side}_performers`, t(side))} data={side === "top" ? top : bottom} titleEditor={editableLabel(`${side}_performers`, t(side), t("performerTitle", { side: t(side) }), t("editPerformerTitle", { side: t(side) }), "h4")} />)}</div></section><section className="analytics-section">{editableTitle("04", "portfolio_analysis", portfolioTitle, portfolioDefault)}<dl className="portfolio-list">{displayPortfolio.map((row) => {
    const editableTurnover = turnoverEnabled && row.metric_code === "AVERAGE_DAILY_TURNOVER";
    return <div key={String(row.metric_code)} className={editableTurnover ? "portfolio-turnover-row" : undefined}><dt>{editableLabel(`portfolio.${row.metric_code}`, String(row.label), t("portfolioMetricTitle", { title: String(row.label) }), t("editPortfolioMetricTitle", { title: String(row.label) }), "span")}</dt><dd>{editableTurnover ? <div className="portfolio-turnover-editor"><input aria-label={String(row.label)} size={16} value={turnover} disabled={busy || frozen} onChange={(event) => setTurnover(event.target.value)} /><button className="icon-button" type="button" aria-label={t("save")} title={t("save")} disabled={busy || frozen || !dirty || !titlesValid} onClick={() => run(persist)}><Save size={16} /></button></div> : <data value={row.raw_value == null ? undefined : String(row.raw_value)}>{portfolioDisplayValue(row) === "N/A" ? t("noData") : portfolioDisplayValue(row)}</data>}</dd></div>;
  })}</dl></section></div><FormulaStrip title={t("analyticsFormula")} formula={t("analyticsFormulaExpression")} detail={t("analyticsFormulaDetail")} /></>;
}

function IndustryMasterStatus({ report }: { report: Report }) {
  const { locale, t, statusLabel } = useLocale();
  const [slot, setSlot] = useState<DatasetSlot | null>(null);
  useEffect(() => {
    api.listDatasets(report.id).then((items) => setSlot(items.find((item) => item.key === "industry_master") ?? null)).catch(() => setSlot(null));
  }, [report.id, report.active_snapshot_id]);
  const state = slot?.state ?? "MISSING";
  return <section className="dataset-upload" aria-label={t("hsicsStatus")}><div className="dataset-slot-head"><div><strong>{locale !== "en" ? t("hsicsMaster") : (slot?.title ?? t("hsicsMaster"))}</strong><span>{locale !== "en" ? t("hsicsHelp") : (slot?.description ?? t("hsicsHelp"))}</span></div><span className={`dataset-state state-${state.toLowerCase()}`}>{statusLabel(state)}</span></div><p className="dataset-current">{slot?.rows ? t("effectiveRecords", { count: slot.rows }) : t("managedCentrally")}</p></section>;
}

function EditableSectionTitle({ index, value, defaultValue, overridden, disabled, onChange, onReset, label, editLabel, heading: Heading = "h3" }: {
  index?: string;
  label?: string;
  editLabel?: string;
  heading?: "h3" | "h4" | "span";
  value: string;
  defaultValue: string;
  overridden: boolean;
  disabled: boolean;
  onChange: (value: string) => void;
  onReset: () => void;
}) {
  const { t } = useLocale();
  const [editing, setEditing] = useState(false);
  const id = useId();
  return <>
    <div className="section-title">
      {index && <span>{index}</span>}<Heading>{value}</Heading>
      <button type="button" className="icon-button" aria-label={editLabel ?? t("editAnalyticsTitle", { index: index ?? "" })}
        title={editLabel ?? t("editAnalyticsTitle", { index: index ?? "" })} aria-expanded={editing} disabled={disabled}
        onClick={() => setEditing((current) => !current)}><Pencil size={16} /></button>
    </div>
    {editing && <div className="analytics-title-editor">
      <label htmlFor={id}>{label ?? t("analyticsSectionTitle", { index: index ?? "" })}</label>
      <MarkerInput id={id} value={value} maxLength={200} required disabled={disabled} onValueChange={onChange} />
      <div className="analytics-title-actions">
        <button type="button" disabled={disabled || !overridden} onClick={onReset}><RotateCcw size={16} /> {t("resetReportTitle", { title: defaultValue })}</button>
        <button type="button" onClick={() => setEditing(false)}>{t("done")}</button>
      </div>
    </div>}
  </>;
}
function PerformerList({ title, data, titleEditor }: { title: string; data: JsonRecord[]; titleEditor?: ReactNode }) { const { locale, t } = useLocale(); const numberLocale = locale === "zh-Hans" ? "zh-CN" : locale === "zh-Hant" ? "zh-HK" : "en-HK"; return <div>{titleEditor ?? <h4>{title}</h4>}{data.map((row, index) => <article key={`${String(row.issuer)}-${index}`}><span>{index + 1}</span><strong>{String(locale === "zh-Hans" ? (row.issuer_zh_hans ?? "") : locale === "zh-Hant" ? (row.issuer_zh_hant ?? "") : (row.issuer ?? ""))}</strong><em>{percent(row.return, numberLocale, t("noData"))}</em></article>)}</div>; }

function footnotesOf(report: Report): Record<FootnoteSectionKey, string> {
  const stored = (sectionsOf(report).footnotes as JsonRecord | undefined) ?? {};
  return Object.fromEntries(FOOTNOTE_SECTIONS.map(({ key }) => [key, typeof stored[key] === "string" ? stored[key] : ""])) as Record<FootnoteSectionKey, string>;
}

function FootnotesModule({ report, busy, run, registerPendingSave = IGNORE_PENDING_SAVE }: Omit<ModuleProps, "active">) {
  const { t } = useLocale();
  const version = report.latest_document?.version ?? 1;
  const content = report.latest_document?.content as JsonRecord | undefined;
  const [footnotes, setFootnotes] = useState(() => footnotesOf(report));
  useEffect(() => setFootnotes(footnotesOf(report)), [report.id, version]);
  const frozen = isReportReadOnly(report);
  const initialFootnotes = useMemo(() => footnotesOf(report), [report.id, version]);
  const persist = useCallback(async () => {
    const next = structuredClone(content ?? {}) as JsonRecord;
    const sections = next.sections as JsonRecord;
    const stored = (sections.footnotes as JsonRecord | undefined) ?? {};
    sections.footnotes = { ...stored, ...footnotes };
    const presentation = next.presentation as PageOnePresentation | undefined;
    if (presentation && [2, 3].includes(presentation.schema_version)) {
      next.presentation = retargetHistoricalFootnoteStyles(
        presentation,
        footnotes.historical,
      );
    }
    await api.saveDocument(report.id, version, next);
  }, [content, footnotes, report.id, version]);
  const dirty = !frozen && JSON.stringify(footnotes) !== JSON.stringify(initialFootnotes);
  useLayoutEffect(() => {
    registerPendingSave(dirty ? persist : null);
    return () => registerPendingSave(null);
  }, [dirty, persist, registerPendingSave]);
  return <>
    <ModuleHeading eyebrow={t("pageDetail", { page: "06", detail: t("freeLayout") })} title={t("footnotes")} description={t("footnoteDescription")} actions={<button className="primary" disabled={busy || frozen || !dirty} onClick={() => run(persist)}><Save size={16} /> {t("saveDisclosures")}</button>} />
    <section className="footnote-list">
      {FOOTNOTE_SECTIONS.map(({ key }) => { const localizedLabel = t(key === "historical" ? "historical" : key === "constituents" ? "constituents" : "analytics"); const localizedBound = key === "historical" ? t("historicalPerformance") : key === "constituents" ? t("constituentPerformance") : t("finalAnalytics"); return <article key={key}>
        <span>{localizedLabel}</span>
        <MarkerTextarea aria-label={t("footnoteLabel", { label: localizedLabel })} value={footnotes[key]} maxLength={10_000} rows={4} disabled={frozen} onValueChange={(value) => setFootnotes((current) => ({ ...current, [key]: value }))} />
        <div>{t("boundTo", { module: localizedBound, version })}</div>
      </article>; })}
    </section>
  </>;
}

function FormulaStrip({ title, formula, detail }: { title: string; formula: string; detail: string }) { return <aside className="formula-strip"><Calculator size={20} /><div><span>{title}</span><strong>{formula}</strong><small>{detail}</small></div></aside>; }
function EmptyData() { const { t } = useLocale(); return <div className="empty-data"><Database size={20} /><span>{t("waitingData")}</span></div>; }
