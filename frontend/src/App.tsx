import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, ChevronDown, Eye, FileCheck2, LoaderCircle, Plus } from "lucide-react";
import { api, type Product, type Report } from "./api";
import { type ModuleId, ModuleNav } from "./components/ModuleNav";
import { ReportModule } from "./components/ReportModulesV2";
import "./styles.css";

const defaultReportDate = "2026-06-30";

function App() {
  const [products, setProducts] = useState<Product[]>([]);
  const [reports, setReports] = useState<Report[]>([]);
  const [selected, setSelected] = useState<Report | null>(null);
  const [productCode, setProductCode] = useState("3033");
  const [reportDate, setReportDate] = useState(defaultReportDate);
  const [activeModule, setActiveModule] = useState<ModuleId>("review");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [review, setReview] = useState<{ ready: boolean; blocking: Array<{ check_id: string; fix_hint: string }> } | null>(null);

  const loadReport = async (id: string) => setSelected(await api.getReport(id));

  useEffect(() => {
    Promise.all([api.listProducts(reportDate), api.listReports()])
      .then(async ([productItems, reportItems]) => {
        setProducts(productItems);
        setReports(reportItems);
        const initial = reportItems[0];
        if (initial) {
          setProductCode(initial.product_code);
          setReportDate(initial.report_date);
          await loadReport(initial.id);
        } else if (productItems[0]) {
          setProductCode(productItems[0].product_code);
        }
      })
      .catch((caught) => setError(String(caught)));
  }, []);

  async function refreshSelected(reportId = selected?.id) {
    const nextReports = await api.listReports();
    setReports(nextReports);
    if (reportId) setSelected(await api.getReport(reportId));
  }

  async function run(work: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try { await work(); await refreshSelected(); }
    catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  }

  const productReports = useMemo(() => reports.filter((report) => report.product_code === productCode), [reports, productCode]);
  const product = products.find((item) => item.product_code === productCode);

  async function selectProduct(nextCode: string) {
    setProductCode(nextCode);
    setReview(null);
    const nextReport = reports.find((report) => report.product_code === nextCode);
    if (nextReport) { setReportDate(nextReport.report_date); await loadReport(nextReport.id); }
    else setSelected(null);
  }

  async function createReport() {
    setBusy(true); setError("");
    try { const created = await api.createReport(reportDate, productCode); await refreshSelected(created.id); }
    catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  }

  async function inspectReview() {
    if (!selected) return;
    setBusy(true); setError("");
    try { setReview(await api.review(selected.id)); }
    catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  }

  const moduleStates = selected ? getModuleStates(selected) : {};

  return <div className="shell"><header className="topbar"><div className="brand"><span className="brand-rule" /><div><span className="eyebrow">REPORT AUTOMATION</span><h1>Monthly Commentary</h1></div></div><div className="topbar-meta"><span>Canonical report workspace</span>{busy && <LoaderCircle className="spin" size={18} aria-label="Working" />}</div></header>{error && <div className="error" role="alert">{error}</div>}<main className="app-main"><section className="report-context"><div className="fund-control"><label htmlFor="fund-select">Fund</label><div className="select-wrap"><select id="fund-select" value={productCode} onChange={(event) => selectProduct(event.target.value)} disabled={busy}>{products.map((item) => <option key={item.id} value={item.product_code}>{item.name_en}</option>)}</select><ChevronDown size={20} aria-hidden="true" /></div><p>{product ? `${product.ticker} · ${product.benchmark_name ?? product.benchmark_code} · ${product.currency}` : selected?.benchmark_code ?? "Select an approved fund"}</p></div><div className="report-controls"><label>Report date<input type="date" value={reportDate} onChange={(event) => setReportDate(event.target.value)} disabled={busy || Boolean(selected)} /></label>{selected && productReports.length > 0 && <label>Report version<select value={selected.id} onChange={(event) => loadReport(event.target.value)}>{productReports.map((report) => <option key={report.id} value={report.id}>{report.report_date} · r{report.version} · {report.status}</option>)}</select></label>}{!selected && <button className="primary" disabled={busy || !product} onClick={createReport}><Plus size={17} /> Create report</button>}{selected && <><button title="Create another report" disabled={busy} onClick={() => { setSelected(null); setReview(null); }}><Plus size={17} /> New report</button><button title="Open canonical preview" onClick={() => window.open(`/api/v1/reports/${selected.id}/preview?v=${selected.latest_document?.version ?? 1}`, "_blank", "noopener,noreferrer")}><Eye size={17} /> Preview</button><button className="primary" disabled={busy} onClick={inspectReview}><FileCheck2 size={17} /> Review & finalize</button></>}</div></section>{selected ? <><section className="status-rail"><div><span className={`status ${selected.status.toLowerCase()}`}>{selected.status}</span><strong>{selected.report_date}</strong><small>{selected.benchmark_code} · document v{selected.latest_document?.version ?? 1}</small></div><div><span>Snapshot</span><strong>{selected.active_snapshot_id ? "Validated" : "Required"}</strong></div><div><span>Quality gates</span><strong>{selected.quality_results?.filter((item) => item.status === "PASSED").length ?? 0}/{selected.quality_results?.length ?? 0}</strong></div><div><span>Artifacts</span><strong>{selected.artifacts?.length ?? 0}</strong></div></section>{review && <section className={review.ready ? "review-result ready" : "review-result blocked"}><div>{review.ready ? <CheckCircle2 size={20} /> : <FileCheck2 size={20} />}<div><strong>{review.ready ? "All blocking gates passed" : `${review.blocking.length} blocking checks remain`}</strong>{!review.ready && <span>{review.blocking.map((item) => item.fix_hint).join(" · ")}</span>}</div></div>{review.ready && selected.status !== "FINALIZED" && <button className="primary" disabled={busy} onClick={() => run(() => api.finalize(selected.id, selected.latest_document?.version ?? 1))}>Finalize report</button>}</section>}<div className="workbench"><ModuleNav active={activeModule} onSelect={setActiveModule} states={moduleStates} /><section className="module-stage"><ReportModule report={selected} active={activeModule} busy={busy} run={run} /></section></div></> : <section className="no-report"><div className="empty-number">00</div><div><span className="eyebrow">NEW REPORT</span><h2>Start a new monthly commentary</h2><p>Choose the reporting date, then create a report. Data and calculations remain empty until a validated source is attached.</p></div></section>}</main></div>;
}

function getModuleStates(report: Report): Partial<Record<ModuleId, "ready" | "attention" | "empty">> {
  const sections = (report.latest_document?.content.sections ?? {}) as Record<string, unknown>;
  const review = (sections.month_in_review ?? {}) as Record<string, unknown>;
  const performance = (sections.historical_performance ?? {}) as Record<string, unknown>;
  const analytics = (sections.analytics ?? {}) as Record<string, unknown>;
  const footnotes = (sections.footnotes ?? {}) as Record<string, unknown>;
  return { review: String(review.summary ?? "").includes("Add the approved") ? "attention" : "ready", performance: Array.isArray(performance.rows) && performance.rows.length ? "ready" : "empty", news: Array.isArray(sections.company_news) && sections.company_news.length ? "ready" : "attention", constituents: Array.isArray(sections.constituents) && sections.constituents.length ? "ready" : "empty", analytics: Array.isArray(analytics.top10) && analytics.top10.length ? "ready" : "empty", footnotes: Object.keys(footnotes).length ? "ready" : "attention" };
}

export default App;
