import { useEffect, useState, type ReactNode } from "react";
import { Calculator, Database, RefreshCw, Save, Sparkles } from "lucide-react";
import { api, type Report } from "../api";
import { NewsWorkbench } from "../features/news/NewsWorkbench";
import { legacyReviewBlocks, ReviewCanvas, type ReviewBlock } from "../features/review/ReviewCanvas";
import { CsvDatasetUpload } from "./CsvDatasetUpload";
import { type ModuleId } from "./ModuleNav";

type RunAction = (work: () => Promise<unknown>) => Promise<void>;
type JsonRecord = Record<string, unknown>;

interface ModuleProps { report: Report; active: ModuleId; busy: boolean; run: RunAction; }

function sectionsOf(report: Report): JsonRecord {
  return (report.latest_document?.content.sections as JsonRecord | undefined) ?? {};
}

function rows(value: unknown): JsonRecord[] { return Array.isArray(value) ? value as JsonRecord[] : []; }
function percent(value: unknown): string { return typeof value === "number" ? new Intl.NumberFormat("en-HK", { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value) : "N/A"; }

function ModuleHeading({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description: string; actions?: ReactNode }) {
  return <header className="module-heading"><div><span className="eyebrow">{eyebrow}</span><h2>{title}</h2><p>{description}</p></div>{actions && <div className="module-actions">{actions}</div>}</header>;
}

export function ReportModule({ report, active, busy, run }: ModuleProps) {
  if (active === "review") return <ReviewModule report={report} busy={busy} run={run} />;
  if (active === "performance") return <PerformanceModule report={report} busy={busy} run={run} />;
  if (active === "news") return <NewsModule report={report} busy={busy} run={run} />;
  if (active === "constituents") return <ConstituentsModule report={report} busy={busy} run={run} />;
  if (active === "analytics") return <AnalyticsModule report={report} busy={busy} run={run} />;
  return <FootnotesModule report={report} />;
}

function ReviewModule({ report, busy, run }: Omit<ModuleProps, "active">) {
  const version = report.latest_document?.version ?? 1;
  const content = report.latest_document?.content as JsonRecord | undefined;
  const review = (sectionsOf(report).month_in_review as JsonRecord | undefined) ?? {};
  const [blocks, setBlocks] = useState<ReviewBlock[]>(() => legacyReviewBlocks(review));
  useEffect(() => setBlocks(legacyReviewBlocks(review)), [version]);
  const save = () => run(async () => {
    const next = structuredClone(content ?? {}) as JsonRecord;
    const section = (next.sections as JsonRecord).month_in_review as JsonRecord;
    section.title = "Review";
    section.display_title = "Review";
    section.layout_schema_version = 2;
    section.blocks = blocks;
    const plainText = (value: string) => value.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    const summary = blocks.find((block) => block.block_id === "summary");
    const outlook = blocks.find((block) => block.block_id === "outlook");
    if (summary) section.summary = plainText(summary.content);
    if (outlook) section.outlook = plainText(outlook.content);
    await api.saveDocument(report.id, version, next);
  });
  return <><ModuleHeading eyebrow="Page 1 · Free layout" title="Review" description="Build the opening page on a controlled 12-column canvas. Drag, resize and edit blocks without changing bound financial facts." actions={<><button disabled={busy || !report.active_snapshot_id || report.status === "FINALIZED"} onClick={() => run(() => api.generateDraft(report.id, version, "Complete the outlook after reviewer confirmation."))}><Sparkles size={16} /> Assisted draft</button><button className="primary" disabled={busy || report.status === "FINALIZED"} onClick={save}><Save size={16} /> Save layout</button></>} /><ReviewCanvas initialBlocks={blocks} disabled={report.status === "FINALIZED"} onChange={setBlocks} /></>;
}

function PerformanceModule({ report, busy, run }: Omit<ModuleProps, "active">) {
  const performance = (sectionsOf(report).historical_performance as JsonRecord | undefined) ?? {};
  const data = rows(performance.rows);
  return <><ModuleHeading eyebrow="Page 1 · Bound metrics" title="Historical Performance" description={`Upload raw FUND and ${report.benchmark_code} Total Return series; calculations remain server-authoritative.`} /><CsvDatasetUpload report={report} datasetType="historical_performance" busy={busy} run={run} /><section className="data-surface"><table><thead><tr><th>Instrument</th><th>1M</th><th>3M</th><th>6M</th><th>YTD</th></tr></thead><tbody>{data.map((row) => <tr key={String(row.name)}><th>{String(row.name)}</th><td>{percent(row.return_1m)}</td><td>{percent(row.return_3m)}</td><td>{percent(row.return_6m)}</td><td>{percent(row.return_ytd)}</td></tr>)}</tbody></table>{!data.length && <EmptyData />}</section><FormulaStrip title="Total return" formula="Return = TR(end) / TR(start) - 1" detail="The server selects common period endpoints and preserves the uploaded series in an immutable snapshot." /></>;
}

function NewsModule({ report, busy, run }: Omit<ModuleProps, "active">) {
  return <><ModuleHeading eyebrow="Page 2 · Curated sources" title="Company News" description="Refresh FMP candidates for current holdings or the general market, then curate report order and wording." /><NewsWorkbench report={report} busy={busy} run={run} selectedSnapshot={rows(sectionsOf(report).company_news)} /></>;
}

function ConstituentsModule({ report, busy, run }: Omit<ModuleProps, "active">) {
  const data = rows(sectionsOf(report).constituents);
  return <><ModuleHeading eyebrow="Page 3 · Snapshot data" title={`The Performance of ${report.benchmark_code} Constituents`} description={`${data.length || "No"} holdings bound to the active immutable snapshot.`} actions={<><button disabled={busy || report.product_code !== "3033" || report.status === "FINALIZED"} onClick={() => run(() => api.createGoldenSnapshot(report.id))}><Database size={16} /> Load approved dataset</button><button className="primary" disabled={busy || !report.active_snapshot_id || report.status === "FINALIZED"} onClick={() => run(() => api.calculate(report.id))}><RefreshCw size={16} /> Recalculate</button></>} /><CsvDatasetUpload report={report} datasetType="constituents" busy={busy} run={run} /><section className="data-surface constituent-table"><table><thead><tr><th>Code</th><th>Constituent</th><th>Price</th><th>Weight</th><th>1M</th><th>3M</th><th>6M</th><th>YTD</th></tr></thead><tbody>{data.map((row) => <tr key={String(row.security_code)}><th><span className="security-code">{String(row.ticker ?? row.security_code)}</span></th><td><strong>{String(row.name_en ?? "")}</strong><small>{String(row.sector ?? "")}</small></td><td>{String(row.currency ?? "")} {Number(row.close_price ?? 0).toFixed(2)}</td><td>{percent(row.weight)}</td><td>{percent(row.return_1m)}</td><td>{percent(row.return_3m)}</td><td>{percent(row.return_6m)}</td><td>{percent(row.return_ytd)}</td></tr>)}</tbody></table>{!data.length && <EmptyData />}</section></>;
}

function AnalyticsModule({ report, busy, run }: Omit<ModuleProps, "active">) {
  const analytics = (sectionsOf(report).analytics as JsonRecord | undefined) ?? {};
  const top10 = rows(analytics.top10); const sectors = rows(analytics.sectors); const top = rows(analytics.top); const bottom = rows(analytics.bottom); const portfolio = rows(analytics.portfolio);
  return <><ModuleHeading eyebrow="Page 4 · Calculated outputs" title="Final Analytics" description="Upload row-level constituents and KPI observations; the server calculates all four report components." /><CsvDatasetUpload report={report} datasetType="final_analytics" busy={busy} run={run} recalculateAfterApply /><div className="analytics-grid"><section className="analytics-section"><SectionTitle index="01" title="Top 10 Index Constituents" /><table><tbody>{top10.map((row, index) => <tr key={`${String(row.issuer)}-${index}`}><th>{String(row.issuer)}</th><td>{percent(row.weight)}</td></tr>)}</tbody></table>{!top10.length && <EmptyData />}</section><section className="analytics-section"><SectionTitle index="02" title="Index Sectors Breakdown" /><div className="sector-list">{sectors.map((row) => <div key={String(row.sector)}><div><span>{String(row.sector)}</span><strong>{percent(row.weight)}</strong></div><i><b style={{ width: percent(row.weight) }} /></i></div>)}</div>{!sectors.length && <EmptyData />}</section><section className="analytics-section"><SectionTitle index="03" title={`Performers in ${new Date(`${report.report_date}T00:00:00`).toLocaleDateString("en-HK", { month: "long" })}`} /><div className="performer-columns"><PerformerList title="Top" data={top} /><PerformerList title="Bottom" data={bottom} /></div></section><section className="analytics-section"><SectionTitle index="04" title={`${report.product_code}.HK Portfolio Analysis`} /><dl className="portfolio-list">{portfolio.map((row) => <div key={String(row.label)}><dt>{String(row.label)}</dt><dd>{String(row.value)}</dd></div>)}</dl>{!portfolio.length && <EmptyData />}</section></div><FormulaStrip title="Analytics calculation set" formula="Weight ranking · Sector aggregation · 1M performer ranking" detail="CSV contains raw observations, never precomputed report sections." /></>;
}

function SectionTitle({ index, title }: { index: string; title: string }) { return <div className="section-title"><span>{index}</span><h3>{title}</h3></div>; }
function PerformerList({ title, data }: { title: string; data: JsonRecord[] }) { return <div><h4>{title}</h4>{data.map((row, index) => <article key={`${String(row.issuer)}-${index}`}><span>{index + 1}</span><strong>{String(row.issuer)}</strong><em>{percent(row.return)}</em></article>)}</div>; }

function FootnotesModule({ report }: { report: Report }) {
  const entries = Object.entries((sectionsOf(report).footnotes as JsonRecord | undefined) ?? {});
  return <><ModuleHeading eyebrow="System-bound disclosures" title="Footnotes & Disclosures" description="Review source dates, formula references and approved legal text before finalization." /><section className="footnote-list">{entries.map(([key, value]) => <article key={key}><span>{key.replaceAll("_", " ")}</span><p>{String(value)}</p><div>Bound to document v{report.latest_document?.version ?? 1}</div></article>)}</section></>;
}

function FormulaStrip({ title, formula, detail }: { title: string; formula: string; detail: string }) { return <aside className="formula-strip"><Calculator size={20} /><div><span>{title}</span><strong>{formula}</strong><small>{detail}</small></div></aside>; }
function EmptyData() { return <div className="empty-data"><Database size={20} /><span>This module is waiting for validated data.</span></div>; }