import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, Download, Eye, FileCheck2, FileOutput, LoaderCircle, Plus } from "lucide-react";
import { api, type Product, type RenderJob, type Report } from "./api";
import { type ModuleId, ModuleNav } from "./components/ModuleNav";
import { ReportModule } from "./components/ReportModulesV2";
import { FOOTNOTE_SECTIONS, reportsForContext } from "./reportModules";
import "./styles.css";

const defaultReportDate = "2026-06-30";

interface ReviewResult {
  ready: boolean;
  blocking: Array<{ check_id: string; fix_hint: string }>;
  warnings: unknown[];
}

function App() {
  const [products, setProducts] = useState<Product[]>([]);
  const [reports, setReports] = useState<Report[]>([]);
  const [selected, setSelected] = useState<Report | null>(null);
  const [productCode, setProductCode] = useState("3033");
  const [reportDate, setReportDate] = useState(defaultReportDate);
  const [activeModule, setActiveModule] = useState<ModuleId>("review");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [review, setReview] = useState<ReviewResult | null>(null);
  const [renderJobs, setRenderJobs] = useState<RenderJob[]>([]);

  const loadReport = async (id: string) => {
    setReview(null);
    setRenderJobs([]);
    setSelected(await api.getReport(id));
  };

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
    try {
      await work();
      await refreshSelected();
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  const productReports = useMemo(
    () => reportsForContext(reports, productCode, reportDate),
    [reports, productCode, reportDate],
  );
  const product = products.find((item) => item.product_code === productCode);

  async function selectProduct(nextCode: string) {
    setProductCode(nextCode);
    setReview(null);
    setRenderJobs([]);
    const nextReport = reportsForContext(reports, nextCode, reportDate)[0];
    if (nextReport) await loadReport(nextReport.id);
    else setSelected(null);
  }

  async function createReport() {
    setBusy(true);
    setError("");
    try {
      const created = await api.createReport(reportDate, productCode);
      await refreshSelected(created.id);
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function inspectReview() {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      setReview(await api.review(selected.id));
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function finalizeAndRender() {
    if (!selected) return;
    await api.finalize(selected.id, selected.latest_document?.version ?? 1);
    setRenderJobs(await api.render(selected.id));
  }

  async function renderAll() {
    if (!selected) return;
    setRenderJobs(await api.render(selected.id));
  }

  const moduleStates = selected ? getModuleStates(selected) : {};
  const artifacts = selected?.artifacts ?? [];

  return <div className="shell">
    <header className="topbar">
      <div className="brand"><span className="brand-rule" /><div><span className="eyebrow">REPORT AUTOMATION</span><h1>Monthly Commentary</h1></div></div>
      <div className="topbar-meta"><span>Canonical report workspace</span>{busy && <LoaderCircle className="spin" size={18} aria-label="Working" />}</div>
    </header>
    {error && <div className="error" role="alert">{error}</div>}
    <main className="app-main">
      <section className="report-context">
        <div className="fund-control">
          <label htmlFor="fund-select">Fund</label>
          <div className="select-wrap"><select id="fund-select" value={productCode} onChange={(event) => void selectProduct(event.target.value)} disabled={busy}>{products.map((item) => <option key={item.id} value={item.product_code}>{item.name_en}</option>)}</select><ChevronDown size={20} aria-hidden="true" /></div>
          <p>{product ? `${product.ticker} · ${product.benchmark_name ?? product.benchmark_code} · ${product.currency}` : selected?.benchmark_code ?? "Select a fund"}</p>
        </div>
        <div className="report-controls">
          <label>Report date<input type="date" value={reportDate} onChange={(event) => setReportDate(event.target.value)} disabled={busy || Boolean(selected)} /></label>
          {selected && productReports.length > 0 && <label>Report version<select value={selected.id} onChange={(event) => void loadReport(event.target.value)}>{productReports.map((report) => <option key={report.id} value={report.id}>{report.report_date} · r{report.version} · {report.status}</option>)}</select></label>}
          {!selected && <button className="primary" disabled={busy || !product} onClick={createReport}><Plus size={17} /> Create report</button>}
          {selected && <>
            <button title="Create another report" disabled={busy} onClick={() => { setSelected(null); setReview(null); setRenderJobs([]); }}><Plus size={17} /> New report</button>
            <button title="Open canonical preview" onClick={() => window.open(`/api/v1/reports/${selected.id}/preview?v=${selected.latest_document?.version ?? 1}`, "_blank", "noopener,noreferrer")}><Eye size={17} /> Preview</button>
            <button className="primary" disabled={busy} onClick={inspectReview}><FileCheck2 size={17} /> Review &amp; finalize</button>
          </>}
        </div>
      </section>

      {selected && <>
        <section className="status-rail">
          <div>
            <span className={`status status-${selected.status.toLowerCase()}`}>{selected.status}</span>
            {selected.lane === "TESTING" && <span className="lane-chip" title="Bound to testing data. Artifacts are watermarked and named TESTING-…"><AlertTriangle size={13} aria-hidden="true" /> TESTING DATA</span>}
            <small>Report lifecycle</small>
          </div>
          <div><span>Snapshot</span><strong>{selected.active_snapshot_id ? "Bound" : "Missing"}</strong></div>
          <div><span>Quality</span><strong>{selected.quality_results?.filter((item) => item.status === "PASSED").length ?? 0}/{selected.quality_results?.length ?? 0}</strong></div>
          <div><span>Artifacts</span><strong>{artifacts.length}</strong></div>
        </section>

        {review && <section className={`review-result ${review.ready ? "ready" : "blocked"}`}>
          <div>{review.ready ? <CheckCircle2 size={22} /> : <AlertTriangle size={22} />}<div><strong>{review.ready ? "Ready to finalize" : `${review.blocking.length} blocking checks`}</strong><span>{review.ready ? "The active snapshot and document passed the release gates." : review.blocking.map((item) => `${item.check_id}: ${item.fix_hint}`).join(" · ")}</span></div></div>
          {review.ready && selected.status !== "FINALIZED" && <button className="primary" disabled={busy} onClick={() => run(finalizeAndRender)}><FileOutput size={17} /> Finalize &amp; generate</button>}
        </section>}

        {selected.status === "FINALIZED" && <section className="artifact-panel">
          <header><div><strong>Report outputs</strong><span>HTML, PDF and DOCX share the finalized content manifest.</span></div><button disabled={busy} onClick={() => run(renderAll)}><FileOutput size={16} /> Generate all</button></header>
          {renderJobs.length > 0 && <div className="render-jobs">{renderJobs.map((job) => <div key={job.id}><span>{job.format.toUpperCase()}</span><strong>{job.status}</strong>{job.error?.message && <small>{job.error.message}</small>}</div>)}</div>}
          <div className="artifact-list">{artifacts.map((artifact) => <article key={artifact.id}><div><strong>{artifact.format.toUpperCase()}</strong><span>{new Intl.NumberFormat("en-HK").format(artifact.size_bytes)} bytes · {artifact.checksum.slice(0, 12)}</span></div><button className="icon-button" title={`Download ${artifact.format.toUpperCase()}`} onClick={() => run(() => api.downloadArtifact(artifact.id))}><Download size={17} /></button></article>)}</div>
        </section>}

        <div className="workbench"><ModuleNav active={activeModule} onSelect={setActiveModule} states={moduleStates} /><section className="module-stage"><ReportModule report={selected} active={activeModule} busy={busy} run={run} /></section></div>
      </>}
    </main>
  </div>;
}

function getModuleStates(report: Report): Partial<Record<ModuleId, "ready" | "attention" | "empty">> {
  const sections = (report.latest_document?.content.sections ?? {}) as Record<string, unknown>;
  const review = (sections.month_in_review ?? {}) as Record<string, unknown>;
  const performance = (sections.historical_performance ?? {}) as Record<string, unknown>;
  const analytics = (sections.analytics ?? {}) as Record<string, unknown>;
  const footnotes = (sections.footnotes ?? {}) as Record<string, unknown>;
  const reviewReady = Boolean(String(review.summary ?? "").trim()) && !String(review.summary ?? "").startsWith("Add ");
  return {
    review: reviewReady ? "ready" : "attention",
    performance: Array.isArray(performance.rows) && performance.rows.length ? "ready" : "empty",
    news: Array.isArray(sections.company_news) && sections.company_news.length ? "ready" : "attention",
    constituents: Array.isArray(sections.constituents) && sections.constituents.length ? "ready" : "empty",
    analytics: Array.isArray(analytics.top10) && analytics.top10.length ? "ready" : "empty",
    footnotes: FOOTNOTE_SECTIONS.every(({ key }) => typeof footnotes[key] === "string" && footnotes[key].trim()) ? "ready" : "attention",
  };
}

export default App;
