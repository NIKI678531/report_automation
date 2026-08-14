import { useCallback, useEffect, useLayoutEffect, useMemo, useState, type ReactNode } from "react";
import { Calculator, Database, RefreshCw, Save, Sparkles } from "lucide-react";
import { api, type DatasetSlot, type Report } from "../api";
import { SectorDonut, sectorSlices, type SectorChartSnapshot } from "../features/analytics/SectorDonut";
import { CompanyNewsWorkbench } from "../features/news/CompanyNewsWorkbench";
import { legacyReviewBlocks, ReviewCanvas, type ReviewBlock } from "../features/review/ReviewCanvas";
import { FOOTNOTE_SECTIONS, reportConstituentsTitle, reportMonthName, reportPageEyebrow, reportProductTicker, type FootnoteSectionKey, type ModuleId } from "../reportModules";
import type { RegisterPendingSave } from "../pendingSave";
import { MultiFileBatchUpload } from "./MultiFileBatchUpload";

type RunAction = (work: () => Promise<unknown>) => Promise<void>;
type JsonRecord = Record<string, unknown>;
const IGNORE_PENDING_SAVE: RegisterPendingSave = () => undefined;

interface ModuleProps { report: Report; active: ModuleId; busy: boolean; run: RunAction; registerPendingSave?: RegisterPendingSave; }

function sectionsOf(report: Report): JsonRecord {
  return (report.latest_document?.content.sections as JsonRecord | undefined) ?? {};
}

function rows(value: unknown): JsonRecord[] { return Array.isArray(value) ? value as JsonRecord[] : []; }
function percent(value: unknown): string {
  const numeric = typeof value === "number" || typeof value === "string" ? Number(value) : Number.NaN;
  return Number.isFinite(numeric) ? new Intl.NumberFormat("en-HK", { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(numeric) : "N/A";
}

function performanceValue(value: unknown): string {
  const numeric = typeof value === "number" || typeof value === "string" ? Number(value) : Number.NaN;
  return Number.isFinite(numeric) ? (numeric * 100).toFixed(2) : "N/A";
}

function priceValue(value: unknown): string {
  const numeric = typeof value === "number" || typeof value === "string" ? Number(value) : Number.NaN;
  return Number.isFinite(numeric) ? numeric.toFixed(2) : "N/A";
}

function constituentName(row: JsonRecord): string {
  for (const value of [row.name_en, row.name_zh_hant]) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "N/A";
}

const PERFORMANCE_ROWS = [
  { role: "FUND", label: "3033.HK" },
  { role: "BENCHMARK", label: "HSTECHN Index" },
] as const;

function ModuleHeading({ eyebrow, title, description, actions }: { eyebrow: string; title: ReactNode; description: string; actions?: ReactNode }) {
  return <header className="module-heading"><div><span className="eyebrow">{eyebrow}</span><h2>{title}</h2><p>{description}</p></div>{actions && <div className="module-actions">{actions}</div>}</header>;
}

function reviewTitleOf(report: Report, review: JsonRecord): string {
  for (const value of [review.display_title, review.title]) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return `${reportMonthName(report)} in Review`;
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

function ReviewModule({ report, busy, run, registerPendingSave = IGNORE_PENDING_SAVE }: Omit<ModuleProps, "active">) {
  const version = report.latest_document?.version ?? 1;
  const content = report.latest_document?.content as JsonRecord | undefined;
  const review = (sectionsOf(report).month_in_review as JsonRecord | undefined) ?? {};
  const [blocks, setBlocks] = useState<ReviewBlock[]>(() => legacyReviewBlocks(review));
  const [reviewTitle, setReviewTitle] = useState(() => reviewTitleOf(report, review));
  const initialBlocks = useMemo(() => legacyReviewBlocks(review), [report.id, version]);
  const initialTitle = useMemo(() => reviewTitleOf(report, review), [report.id, version]);
  useEffect(() => {
    setBlocks(legacyReviewBlocks(review));
    setReviewTitle(reviewTitleOf(report, review));
  }, [report.id, version]);
  const persist = useCallback(async () => {
    const next = structuredClone(content ?? {}) as JsonRecord;
    const section = (next.sections as JsonRecord).month_in_review as JsonRecord;
    const normalizedTitle = reviewTitle.trim();
    section.title = normalizedTitle;
    section.display_title = normalizedTitle;
    section.layout_schema_version = 2;
    section.blocks = blocks;
    const plainText = (value: string) => value.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    const summary = blocks.find((block) => block.block_id === "summary");
    const outlook = blocks.find((block) => block.block_id === "outlook");
    if (summary) section.summary = plainText(summary.content);
    if (outlook) section.outlook = plainText(outlook.content);
    await api.saveDocument(report.id, version, next);
  }, [blocks, content, report.id, reviewTitle, version]);
  const frozen = report.status === "FINALIZED";
  const dirty = !frozen && (reviewTitle !== initialTitle || JSON.stringify(blocks) !== JSON.stringify(initialBlocks));
  useLayoutEffect(() => {
    registerPendingSave(dirty ? persist : null);
    return () => registerPendingSave(null);
  }, [dirty, persist, registerPendingSave]);
  return <><ModuleHeading eyebrow={reportPageEyebrow("review", "Free layout")} title={<input className="review-title-input" aria-label="Page 1 review title" value={reviewTitle} maxLength={200} required disabled={frozen} onChange={(event) => setReviewTitle(event.target.value)} />} description="Build the opening page on a controlled 12-column canvas. Drag, resize and edit blocks without changing bound financial facts." actions={<><button disabled={busy || !report.active_snapshot_id || frozen} onClick={() => run(() => api.generateDraft(report.id, version, "Complete the outlook after reviewer confirmation."))}><Sparkles size={16} /> Assisted draft</button><button className="primary" disabled={busy || frozen || !reviewTitle.trim() || !dirty} onClick={() => run(persist)}><Save size={16} /> Save layout</button></>} /><ReviewCanvas initialBlocks={blocks} disabled={frozen} onChange={setBlocks} /></>;
}

function PerformanceModule({ report, busy, run }: Omit<ModuleProps, "active">) {
  const performance = (sectionsOf(report).historical_performance as JsonRecord | undefined) ?? {};
  const data = rows(performance.rows);
  return <>
    <ModuleHeading
      eyebrow={reportPageEyebrow("performance", "CSOP data warehouse")}
      title="Historical Performance"
      description={`3033.HK product returns and ${report.benchmark_instrument_code} benchmark returns are read from the approved warehouse views.`}
      actions={<button disabled={busy || report.status === "FINALIZED"} onClick={() => run(() => api.refreshAutomaticData(report.id, report.version))}><RefreshCw size={16} /> Refresh data warehouse</button>}
    />
    <section className="data-surface performance-table" aria-labelledby="performance-table-title">
      <h3 id="performance-table-title" className="performance-table-title">Historical Performance of 3033.HK and Hang Seng TECH Index*</h3>
      <table>
        <colgroup><col /><col /><col /><col /><col /></colgroup>
        <thead><tr><th aria-label="Instrument"></th><th>1-month return (%)</th><th>3-month return (%)</th><th>6-month return (%)</th><th>YTD return (%)</th></tr></thead>
        <tbody>{PERFORMANCE_ROWS.map(({ role, label }, index) => {
          const row = data.find((candidate) => candidate.role === role) ?? data[index] ?? {};
          return <tr key={role}><th scope="row">{label}</th><td>{performanceValue(row.return_1m)}</td><td>{performanceValue(row.return_3m)}</td><td>{performanceValue(row.return_6m)}</td><td>{performanceValue(row.return_ytd)}</td></tr>;
        })}</tbody>
      </table>
      {!data.length && <EmptyData message="The selected warehouse snapshot contains no matching 3033.HK and HSTECHN Index return rows." />}
    </section>
  </>;
}

function NewsModule({ report, busy, run, registerPendingSave = IGNORE_PENDING_SAVE }: Omit<ModuleProps, "active">) {
  return <><ModuleHeading eyebrow={reportPageEyebrow("news", "DA-Report catalog")} title="Company News" description="Browse the complete Regional Corporate catalog, then order and edit selected stories before saving." /><CompanyNewsWorkbench key={report.id} report={report} busy={busy} run={run} selectedSnapshot={rows(sectionsOf(report).company_news)} registerPendingSave={registerPendingSave} /></>;
}

function ConstituentsModule({ report, busy, run }: Omit<ModuleProps, "active">) {
  const data = rows(sectionsOf(report).constituents);
  return <><ModuleHeading eyebrow={reportPageEyebrow("constituents", "Required upload")} title={reportConstituentsTitle(report)} description={data.length ? `${data.length} validated holdings are bound to the active immutable snapshot and drive Final Analytics.` : "A validated HSTECH constituent upload is mandatory before analysis. No draft or sample holdings are substituted."} /><MultiFileBatchUpload report={report} busy={busy} run={run} hasCurrentData={data.length > 0} /><section className="data-surface constituent-table"><table><thead><tr><th>Stock Code</th><th>Stock Name</th><th>Closing Price (HKD)</th><th>Weighting (%)</th><th>1-month return (%)</th><th>3-month return (%)</th><th>6-month return (%)</th><th>YTD return (%)</th></tr></thead><tbody>{data.map((row) => <tr key={String(row.security_code)}><th scope="row"><span className="security-code">{String(row.security_code ?? "N/A")}</span></th><td><strong>{constituentName(row)}</strong></td><td>{priceValue(row.close_price)}</td><td>{performanceValue(row.weight)}</td><td>{performanceValue(row.return_1m)}</td><td>{performanceValue(row.return_3m)}</td><td>{performanceValue(row.return_6m)}</td><td>{performanceValue(row.return_ytd)}</td></tr>)}</tbody></table>{!data.length && <EmptyData message="Upload and apply Page 04 constituent identity and return data to continue." />}</section></>;
}

function AnalyticsModule({ report }: Omit<ModuleProps, "active">) {
  const analytics = (sectionsOf(report).analytics as JsonRecord | undefined) ?? {};
  const top10 = rows(analytics.top10); const top = rows(analytics.top); const bottom = rows(analytics.bottom); const portfolio = rows(analytics.portfolio);
  const sectorChart = analytics.sector_chart as SectorChartSnapshot | undefined;
  const sectorSeries = sectorSlices(sectorChart);
  const monthName = reportMonthName(report);
  const productTicker = reportProductTicker(report);
  return <><ModuleHeading eyebrow={reportPageEyebrow("analytics", "Calculated outputs")} title="Final Analytics" description="Derived only from the validated Page 04 upload. Top 10, sectors and performers never use draft, fixture or hard-coded fallback values." />{!top10.length && <AnalysisDependencyNotice />}<IndustryMasterStatus report={report} /><div className="analytics-grid"><section className="analytics-section"><SectionTitle index="01" title="Top 10 Index Constituents" /><table><tbody>{top10.map((row, index) => <tr key={`${String(row.issuer)}-${index}`}><th>{String(row.issuer)}</th><td>{percent(row.weight)}</td></tr>)}</tbody></table>{!top10.length && <EmptyData message="Waiting for the validated Page 04 upload." />}</section><section className="analytics-section"><SectionTitle index="02" title="Index Sectors Breakdown" />{sectorSeries.length ? <SectorDonut chart={sectorChart} /> : <EmptyData message="The sector chart is generated from uploaded weights and effective HSICS codes." />}</section><section className="analytics-section"><SectionTitle index="03" title={`Performers in ${monthName}`} /><div className="performer-columns"><PerformerList title="Top" data={top} /><PerformerList title="Bottom" data={bottom} /></div></section><section className="analytics-section"><SectionTitle index="04" title={`${productTicker} Portfolio Analysis`} /><dl className="portfolio-list">{portfolio.map((row) => <div key={String(row.label)}><dt>{String(row.label)}</dt><dd>{String(row.value)}</dd></div>)}</dl>{!portfolio.length && <EmptyData message="No KPI or holding facts have been validated yet." />}</section></div><FormulaStrip title="Analytics calculation set" formula="Weight ranking · HSICS aggregation · 1M performer ranking" detail="Every output is recalculated when a new Page 04 upload is applied; missing KPI values stay empty." /></>;
}

function AnalysisDependencyNotice() {
  return <section className="analysis-dependency" role="status"><Database size={18} /><div><strong>Page 04 upload required</strong><span>Apply validated HSTECH constituents and returns before Final Analytics can be generated.</span></div></section>;
}

function IndustryMasterStatus({ report }: { report: Report }) {
  const [slot, setSlot] = useState<DatasetSlot | null>(null);
  useEffect(() => {
    api.listDatasets(report.id).then((items) => setSlot(items.find((item) => item.key === "industry_master") ?? null)).catch(() => setSlot(null));
  }, [report.id, report.active_snapshot_id]);
  const state = slot?.state ?? "MISSING";
  return <section className="dataset-upload" aria-label="HSICS industry master status"><div className="dataset-slot-head"><div><strong>{slot?.title ?? "HSICS industry master"}</strong><span>{slot?.description ?? "A report-date-effective taxonomy is required before analysis."}</span></div><span className={`dataset-state state-${state.toLowerCase()}`}>{state}</span></div><p className="dataset-current">{slot?.rows ? `${slot.rows} effective records` : "Managed through the central industry-master import."}</p></section>;
}

function SectionTitle({ index, title }: { index: string; title: string }) { return <div className="section-title"><span>{index}</span><h3>{title}</h3></div>; }
function PerformerList({ title, data }: { title: string; data: JsonRecord[] }) { return <div><h4>{title}</h4>{data.map((row, index) => <article key={`${String(row.issuer)}-${index}`}><span>{index + 1}</span><strong>{String(row.issuer)}</strong><em>{percent(row.return)}</em></article>)}</div>; }

function footnotesOf(report: Report): Record<FootnoteSectionKey, string> {
  const stored = (sectionsOf(report).footnotes as JsonRecord | undefined) ?? {};
  return Object.fromEntries(FOOTNOTE_SECTIONS.map(({ key }) => [key, typeof stored[key] === "string" ? stored[key] : ""])) as Record<FootnoteSectionKey, string>;
}

function FootnotesModule({ report, busy, run, registerPendingSave = IGNORE_PENDING_SAVE }: Omit<ModuleProps, "active">) {
  const version = report.latest_document?.version ?? 1;
  const content = report.latest_document?.content as JsonRecord | undefined;
  const [footnotes, setFootnotes] = useState(() => footnotesOf(report));
  useEffect(() => setFootnotes(footnotesOf(report)), [report.id, version]);
  const frozen = report.status === "FINALIZED";
  const initialFootnotes = useMemo(() => footnotesOf(report), [report.id, version]);
  const persist = useCallback(async () => {
    const next = structuredClone(content ?? {}) as JsonRecord;
    const sections = next.sections as JsonRecord;
    const stored = (sections.footnotes as JsonRecord | undefined) ?? {};
    sections.footnotes = { ...stored, ...footnotes };
    await api.saveDocument(report.id, version, next);
  }, [content, footnotes, report.id, version]);
  const dirty = !frozen && JSON.stringify(footnotes) !== JSON.stringify(initialFootnotes);
  useLayoutEffect(() => {
    registerPendingSave(dirty ? persist : null);
    return () => registerPendingSave(null);
  }, [dirty, persist, registerPendingSave]);
  return <>
    <ModuleHeading eyebrow={reportPageEyebrow("footnotes", "Free layout")} title="Footnotes & Disclosures" description="Edit the three disclosures below. Each field keeps its source module binding and uses only the current product report data." actions={<button className="primary" disabled={busy || frozen || !dirty} onClick={() => run(persist)}><Save size={16} /> Save disclosures</button>} />
    <section className="footnote-list">
      {FOOTNOTE_SECTIONS.map(({ key, label, boundTo }) => <article key={key}>
        <span>{label}</span>
        <textarea aria-label={`${label} footnote`} value={footnotes[key]} maxLength={10_000} rows={4} disabled={frozen} onChange={(event) => setFootnotes((current) => ({ ...current, [key]: event.target.value }))} />
        <div>Bound to {boundTo} · document v{version}</div>
      </article>)}
    </section>
  </>;
}

function FormulaStrip({ title, formula, detail }: { title: string; formula: string; detail: string }) { return <aside className="formula-strip"><Calculator size={20} /><div><span>{title}</span><strong>{formula}</strong><small>{detail}</small></div></aside>; }
function EmptyData({ message = "This module is waiting for validated data." }: { message?: string }) { return <div className="empty-data"><Database size={20} /><span>{message}</span></div>; }
