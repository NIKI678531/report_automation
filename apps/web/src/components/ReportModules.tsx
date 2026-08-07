import { useEffect, useState, type ReactNode } from "react";
import {
  ArrowDown,
  ArrowUp,
  Calculator,
  Check,
  Database,
  FileUp,
  GripVertical,
  Link2,
  Plus,
  RefreshCw,
  Save,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { api, type NewsCandidate, type Report } from "../api";
import { type ModuleId } from "./ModuleNav";

type RunAction = (work: () => Promise<unknown>) => Promise<void>;
type JsonRecord = Record<string, unknown>;

interface ModuleProps {
  report: Report;
  active: ModuleId;
  busy: boolean;
  run: RunAction;
}

function sectionsOf(report: Report): JsonRecord {
  const content = report.latest_document?.content;
  return (content?.sections as JsonRecord | undefined) ?? {};
}

function asRows(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value as JsonRecord[] : [];
}

function percent(value: unknown): string {
  return typeof value === "number"
    ? new Intl.NumberFormat("en-HK", { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)
    : "N/A";
}

function ModuleHeading({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description: string; actions?: ReactNode }) {
  return <header className="module-heading"><div><span className="eyebrow">{eyebrow}</span><h2>{title}</h2><p>{description}</p></div>{actions && <div className="module-actions">{actions}</div>}</header>;
}

export function ReportModule({ report, active, busy, run }: ModuleProps) {
  if (active === "review") return <ReviewModule report={report} busy={busy} run={run} />;
  if (active === "performance") return <PerformanceModule report={report} />;
  if (active === "news") return <NewsModule report={report} busy={busy} run={run} />;
  if (active === "constituents") return <ConstituentsModule report={report} busy={busy} run={run} />;
  if (active === "analytics") return <AnalyticsModule report={report} />;
  return <FootnotesModule report={report} />;
}

function ReviewModule({ report, busy, run }: Omit<ModuleProps, "active">) {
  const version = report.latest_document?.version ?? 1;
  const content = report.latest_document?.content as JsonRecord | undefined;
  const month = (sectionsOf(report).month_in_review as JsonRecord | undefined) ?? {};
  const defaultOrder = ["summary", "drivers", "monitor", "outlook"];
  const [summary, setSummary] = useState(String(month.summary ?? ""));
  const [order, setOrder] = useState<string[]>(Array.isArray(month.layout_order) ? month.layout_order as string[] : defaultOrder);
  const [dragged, setDragged] = useState<string | null>(null);

  useEffect(() => {
    setSummary(String(month.summary ?? ""));
    setOrder(Array.isArray(month.layout_order) ? month.layout_order as string[] : defaultOrder);
  }, [version]);

  const move = (id: string, direction: -1 | 1) => setOrder((current) => {
    const index = current.indexOf(id);
    const target = index + direction;
    if (target < 0 || target >= current.length) return current;
    const next = [...current];
    [next[index], next[target]] = [next[target], next[index]];
    return next;
  });

  const drop = (target: string) => {
    if (!dragged || dragged === target) return;
    setOrder((current) => {
      const next = current.filter((item) => item !== dragged);
      next.splice(next.indexOf(target), 0, dragged);
      return next;
    });
    setDragged(null);
  };

  const save = () => run(async () => {
    const next = structuredClone(content ?? {}) as JsonRecord;
    const sections = next.sections as JsonRecord;
    const review = sections.month_in_review as JsonRecord;
    review.summary = summary;
    review.layout_order = order;
    await api.saveDocument(report.id, version, next);
  });

  const blocks: Record<string, { label: string; span: string; body: ReactNode }> = {
    summary: { label: "Monthly summary", span: "span-12", body: <textarea value={summary} disabled={report.status === "FINALIZED"} onChange={(event) => setSummary(event.target.value)} aria-label="Monthly summary" /> },
    drivers: { label: "Key Drivers", span: "span-6", body: <EditorialList rows={asRows(month.drivers)} /> },
    monitor: { label: "Key Areas to Monitor", span: "span-6", body: <EditorialList rows={asRows(month.monitor)} /> },
    outlook: { label: "Outlook", span: "span-6", body: <p className="editable-copy">{String(month.outlook ?? "No outlook drafted.")}</p> },
  };

  return <>
    <ModuleHeading eyebrow="Page 1 · Editorial layout" title={String(month.title ?? "Month in Review")} description="Compose the opening narrative from controlled content blocks and bound report data." actions={<><button disabled={busy || !report.active_snapshot_id || report.status === "FINALIZED"} onClick={() => run(() => api.generateDraft(report.id, version, "Complete the outlook after reviewer confirmation."))}><Sparkles size={16} /> Assisted draft</button><button className="primary" disabled={busy || report.status === "FINALIZED"} onClick={save}><Save size={16} /> Save version</button></>} />
    <div className="section-canvas" aria-label="Twelve-column section layout">
      {order.map((id, index) => { const block = blocks[id]; if (!block) return null; return <section key={id} className={`content-block ${block.span}`} draggable={report.status !== "FINALIZED"} onDragStart={() => setDragged(id)} onDragOver={(event) => event.preventDefault()} onDrop={() => drop(id)}><div className="block-toolbar"><GripVertical size={17} aria-hidden="true" /><strong>{block.label}</strong><span className="column-tag">{block.span === "span-12" ? "12 cols" : "6 cols"}</span><button className="icon-button" title="Move block up" aria-label={`Move ${block.label} up`} disabled={index === 0 || report.status === "FINALIZED"} onClick={() => move(id, -1)}><ArrowUp size={15} /></button><button className="icon-button" title="Move block down" aria-label={`Move ${block.label} down`} disabled={index === order.length - 1 || report.status === "FINALIZED"} onClick={() => move(id, 1)}><ArrowDown size={15} /></button></div><div className="block-content">{block.body}</div></section>; })}
    </div>
  </>;
}

function EditorialList({ rows }: { rows: JsonRecord[] }) {
  if (!rows.length) return <p className="empty-copy">No approved content yet.</p>;
  return <div className="editorial-list">{rows.map((row, index) => <article key={`${String(row.title)}-${index}`}><h4>{String(row.title ?? "")}</h4><p>{String(row.body ?? "")}</p></article>)}</div>;
}

function PerformanceModule({ report }: { report: Report }) {
  const performance = (sectionsOf(report).historical_performance as JsonRecord | undefined) ?? {};
  const rows = asRows(performance.rows);
  return <><ModuleHeading eyebrow="Page 1 · Bound metrics" title="Historical Performance" description={`Fund and ${report.benchmark_code} returns use the same approved period boundaries.`} /><section className="data-surface"><table><thead><tr><th>Instrument</th><th>1M</th><th>3M</th><th>6M</th><th>YTD</th></tr></thead><tbody>{rows.map((row) => <tr key={String(row.name)}><th>{String(row.name)}</th><td>{percent(row.return_1m)}</td><td>{percent(row.return_3m)}</td><td>{percent(row.return_6m)}</td><td>{percent(row.return_ytd)}</td></tr>)}</tbody></table>{!rows.length && <EmptyData />}</section><FormulaStrip title="Total return" formula="Return = TR(end) / TR(start) - 1" detail="Fund and benchmark share the latest common trading-date endpoints." /></>;
}

function NewsModule({ report, busy, run }: Omit<ModuleProps, "active">) {
  const version = report.latest_document?.version ?? 1;
  const selectedSnapshot = asRows(sectionsOf(report).company_news);
  const [candidates, setCandidates] = useState<NewsCandidate[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>(selectedSnapshot.map((item) => String(item.news_item_id ?? "")).filter(Boolean));
  const [query, setQuery] = useState("");
  useEffect(() => { api.listNews().then(setCandidates).catch(() => setCandidates([])); }, [report.id, version]);
  useEffect(() => setSelectedIds(selectedSnapshot.map((item) => String(item.news_item_id ?? "")).filter(Boolean)), [version]);
  const visible = candidates.filter((item) => `${item.title} ${item.summary} ${item.ticker ?? ""}`.toLowerCase().includes(query.toLowerCase()));
  const moveSelected = (id: string, direction: -1 | 1) => setSelectedIds((current) => { const index = current.indexOf(id); const target = index + direction; if (target < 0 || target >= current.length) return current; const next = [...current]; [next[index], next[target]] = [next[target], next[index]]; return next; });
  return <><ModuleHeading eyebrow="Page 2 · Curated sources" title="Company News" description="Select, order and review constituent news while retaining source evidence." actions={<button className="primary" disabled={busy || report.status === "FINALIZED" || !selectedIds.length} onClick={() => run(() => api.selectNews(report.id, version, selectedIds))}><Save size={16} /> Save selection</button>} /><div className="news-workbench"><section className="news-column"><div className="surface-heading"><div><span>Candidate library</span><strong>{visible.length}</strong></div><label className="search-field"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search company, ticker or headline" /></label></div><div className="news-list">{visible.map((item) => <article className="news-item" key={item.id}><div><span className={`importance ${item.importance.toLowerCase()}`}>{item.importance}</span><time>{new Date(item.published_at).toLocaleDateString("en-HK")}</time></div><h3>{item.title}</h3><p>{item.summary}</p><footer><span><Link2 size={14} /> {item.source_name}</span><button className="icon-button" title="Add to report" aria-label={`Add ${item.title}`} disabled={selectedIds.includes(item.id)} onClick={() => setSelectedIds((current) => [...current, item.id])}>{selectedIds.includes(item.id) ? <Check size={16} /> : <Plus size={16} />}</button></footer></article>)}{!visible.length && <EmptyData label="No news candidates match this report." />}</div></section><section className="news-column selected-news"><div className="surface-heading"><div><span>Selected for report</span><strong>{selectedSnapshot.length + selectedIds.length}</strong></div></div><div className="news-list">{selectedSnapshot.filter((item) => !item.news_item_id).map((item, index) => <article className="news-item frozen" key={`${String(item.title)}-${index}`}><span className="snapshot-tag">Snapshot</span><h3>{String(item.title ?? "")}</h3><p>{String(item.summary ?? "")}</p></article>)}{selectedIds.map((id, index) => { const item = candidates.find((candidate) => candidate.id === id); if (!item) return null; return <article className="news-item selected" key={id}><div className="selection-order">{String(index + 1).padStart(2, "0")}</div><h3>{item.title}</h3><footer><span>{item.source_name}</span><div><button className="icon-button" title="Move up" aria-label={`Move ${item.title} up`} disabled={index === 0} onClick={() => moveSelected(id, -1)}><ArrowUp size={15} /></button><button className="icon-button" title="Move down" aria-label={`Move ${item.title} down`} disabled={index === selectedIds.length - 1} onClick={() => moveSelected(id, 1)}><ArrowDown size={15} /></button><button className="icon-button danger" title="Remove" aria-label={`Remove ${item.title}`} onClick={() => setSelectedIds((current) => current.filter((value) => value !== id))}><X size={15} /></button></div></footer></article>; })}{!selectedSnapshot.length && !selectedIds.length && <EmptyData label="No news selected." />}</div></section></div></>;
}

function ConstituentsModule({ report, busy, run }: Omit<ModuleProps, "active">) {
  const rows = asRows(sectionsOf(report).constituents);
  const [importId, setImportId] = useState(""); const [uploadResult, setUploadResult] = useState(""); const [reason, setReason] = useState("");
  return <><ModuleHeading eyebrow="Page 3 · Snapshot data" title={`The Performance of ${report.benchmark_code} Constituents`} description={`${rows.length || "No"} holdings bound to the active immutable snapshot.`} actions={<><label className="button-like"><FileUp size={16} /> Import dataset<input type="file" accept=".csv,.xlsx,.xlsm" disabled={busy || report.status === "FINALIZED"} onChange={(event) => { const file = event.target.files?.[0]; if (file) run(async () => { const result = await api.uploadConstituents(report.id, file); setImportId(result.id); setUploadResult(`${result.diff.summary.added} added · ${result.diff.summary.removed} removed · ${result.diff.summary.changed} changed`); }); }} /></label><button disabled={busy || report.product_code !== "3033" || report.status === "FINALIZED"} onClick={() => run(() => api.createGoldenSnapshot(report.id))}><Database size={16} /> Load approved dataset</button><button className="primary" disabled={busy || !report.active_snapshot_id || report.status === "FINALIZED"} onClick={() => run(() => api.calculate(report.id))}><RefreshCw size={16} /> Recalculate</button></>} />{uploadResult && <div className="import-review"><div><strong>Validated import</strong><span>{uploadResult}</span></div>{importId && <><input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Approved override reason" /><button disabled={reason.trim().length < 5} onClick={() => run(async () => { await api.applyImport(report.id, importId, reason); setImportId(""); setReason(""); setUploadResult(""); })}><Check size={16} /> Apply as new snapshot</button></>}</div>}<section className="data-surface constituent-table"><table><thead><tr><th>Code</th><th>Constituent</th><th>Price</th><th>Weight</th><th>1M</th><th>3M</th><th>6M</th><th>YTD</th></tr></thead><tbody>{rows.map((row) => <tr key={String(row.security_code)}><th><span className="security-code">{String(row.ticker ?? row.security_code)}</span></th><td><strong>{String(row.name_en ?? "")}</strong><small>{String(row.sector ?? "")}</small></td><td>{String(row.currency ?? "")} {Number(row.close_price ?? 0).toFixed(2)}</td><td>{percent(row.weight)}</td><td>{percent(row.return_1m)}</td><td>{percent(row.return_3m)}</td><td>{percent(row.return_6m)}</td><td>{percent(row.return_ytd)}</td></tr>)}</tbody></table>{!rows.length && <EmptyData />}</section><FormulaStrip title="Constituent period return" formula="Return = TR(end) / TR(start) - 1" detail="Ranks are stable by return, weight and security code. Missing history remains N/A." /></>;
}

function AnalyticsModule({ report }: { report: Report }) {
  const analytics = (sectionsOf(report).analytics as JsonRecord | undefined) ?? {};
  const top10 = asRows(analytics.top10); const sectors = asRows(analytics.sectors); const top = asRows(analytics.top); const bottom = asRows(analytics.bottom); const portfolio = asRows(analytics.portfolio);
  return <><ModuleHeading eyebrow="Page 4 · Calculated outputs" title="Final Analytics" description={`Four report components calculated from the ${report.benchmark_code} snapshot.`} /><div className="analytics-grid"><section className="analytics-section"><div className="section-title"><span>01</span><h3>Top 10 Index Constituents</h3></div><table><tbody>{top10.map((row, index) => <tr key={`${String(row.issuer)}-${index}`}><th>{String(row.issuer)}</th><td>{percent(row.weight)}</td></tr>)}</tbody></table>{!top10.length && <EmptyData />}</section><section className="analytics-section"><div className="section-title"><span>02</span><h3>Index Sectors Breakdown</h3></div><div className="sector-list">{sectors.map((row) => <div key={String(row.sector)}><div><span>{String(row.sector)}</span><strong>{percent(row.weight)}</strong></div><i><b style={{ width: percent(row.weight) }} /></i></div>)}</div>{!sectors.length && <EmptyData />}</section><section className="analytics-section"><div className="section-title"><span>03</span><h3>Performers in {new Date(`${report.report_date}T00:00:00`).toLocaleDateString("en-HK", { month: "long" })}</h3></div><div className="performer-columns"><PerformerList title="Top" rows={top} /><PerformerList title="Bottom" rows={bottom} /></div></section><section className="analytics-section"><div className="section-title"><span>04</span><h3>{report.product_code}.HK Portfolio Analysis</h3></div><dl className="portfolio-list">{portfolio.map((row) => <div key={String(row.label)}><dt>{String(row.label)}</dt><dd>{String(row.value)}</dd></div>)}</dl>{!portfolio.length && <EmptyData />}</section></div><FormulaStrip title="Analytics calculation set" formula="Weight ranking · Sector aggregation · 1M performer ranking" detail={`Formula profile ${String((report.latest_document?.content as JsonRecord | undefined)?.formula_version ?? "pending calculation")}.`} /></>;
}

function PerformerList({ title, rows }: { title: string; rows: JsonRecord[] }) {
  return <div><h4>{title}</h4>{rows.map((row, index) => <article key={`${String(row.issuer)}-${index}`}><span>{index + 1}</span><strong>{String(row.issuer)}</strong><em>{percent(row.return)}</em></article>)}{!rows.length && <EmptyData />}</div>;
}

function FootnotesModule({ report }: { report: Report }) {
  const footnotes = (sectionsOf(report).footnotes as JsonRecord | undefined) ?? {};
  const entries = Object.entries(footnotes);
  return <><ModuleHeading eyebrow="System-bound disclosures" title="Footnotes & Disclosures" description="Review source dates, formula references and approved legal text before finalization." /><section className="footnote-list">{entries.map(([key, value]) => <article key={key}><span>{key.replaceAll("_", " ")}</span><p>{String(value)}</p><div><Link2 size={14} /> Bound to document v{report.latest_document?.version ?? 1}</div></article>)}{!entries.length && <EmptyData label="No footnotes are bound to this report." />}</section></>;
}

function FormulaStrip({ title, formula, detail }: { title: string; formula: string; detail: string }) {
  return <aside className="formula-strip"><Calculator size={20} /><div><span>{title}</span><strong>{formula}</strong><small>{detail}</small></div></aside>;
}

function EmptyData({ label = "This module is waiting for a validated snapshot." }: { label?: string }) {
  return <div className="empty-data"><Database size={20} /><span>{label}</span></div>;
}