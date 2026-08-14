import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Download, Eye, FileCheck2, FileOutput, LoaderCircle, Plus } from "lucide-react";
import { api, type OutputFormat, type Product, type RenderJob, type Report } from "./api";
import { type ModuleId, ModuleNav } from "./components/ModuleNav";
import { ReportModule } from "./components/ReportModulesV2";
import type { PendingSave, RegisterPendingSave } from "./pendingSave";
import { FOOTNOTE_SECTIONS, reportsForContext, selectInitialReport, selectReportForMonth } from "./reportModules";
import "./styles.css";

const PRODUCT_CODE = "3033";
const OUTPUT_FORMATS: Array<{ value: OutputFormat; label: string }> = [
  { value: "pdf", label: "PDF" },
  { value: "html", label: "HTML" },
  { value: "docx", label: "Word (.docx)" },
];

function reportMonthEnd(value: string): string {
  const [year, month] = value.split("-").map(Number);
  const day = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return `${value}-${String(day).padStart(2, "0")}`;
}

function currentHongKongMonthEnd(): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Hong_Kong",
    year: "numeric",
    month: "2-digit",
  }).formatToParts(new Date());
  const year = parts.find((part) => part.type === "year")?.value;
  const month = parts.find((part) => part.type === "month")?.value;
  return reportMonthEnd(`${year ?? "1970"}-${month ?? "01"}`);
}

function formatLabel(format: OutputFormat): string {
  return OUTPUT_FORMATS.find((item) => item.value === format)?.label ?? format.toUpperCase();
}

function isTerminal(job: RenderJob): boolean {
  return ["SUCCEEDED", "FAILED", "CANCELED"].includes(job.status);
}

interface ReviewResult {
  ready: boolean;
  blocking: Array<{ check_id: string; fix_hint: string }>;
  warnings: Array<{ check_id?: string; fix_hint?: string }>;
}

function App() {
  const [products, setProducts] = useState<Product[]>([]);
  const [reports, setReports] = useState<Report[]>([]);
  const [selected, setSelected] = useState<Report | null>(null);
  const [reportDate, setReportDate] = useState(currentHongKongMonthEnd);
  const [activeModule, setActiveModule] = useState<ModuleId>("review");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [review, setReview] = useState<ReviewResult | null>(null);
  const [renderJobs, setRenderJobs] = useState<RenderJob[]>([]);
  const [selectedFormats, setSelectedFormats] = useState<OutputFormat[]>(["pdf"]);
  const [outputsOpen, setOutputsOpen] = useState(false);
  const pendingSave = useRef<PendingSave | null>(null);
  const outputPanel = useRef<HTMLElement>(null);

  const registerPendingSave = useCallback<RegisterPendingSave>((save) => {
    pendingSave.current = save;
  }, []);

  const resetTransientState = useCallback(() => {
    pendingSave.current = null;
    setReview(null);
    setRenderJobs([]);
    setOutputsOpen(false);
  }, []);

  const refreshReport = useCallback(async (reportId: string): Promise<Report> => {
    const [nextReports, detail] = await Promise.all([api.listReports(), api.getReport(reportId)]);
    setReports(nextReports);
    setSelected(detail);
    return detail;
  }, []);

  useEffect(() => {
    let active = true;
    void api.listReports()
      .then(async (reportItems) => {
        const initial = selectInitialReport(reportItems, PRODUCT_CODE);
        const initialDate = initial?.report_date ?? currentHongKongMonthEnd();
        const [productItems, detail] = await Promise.all([
          api.listProducts(initialDate),
          initial ? api.getReport(initial.id) : Promise.resolve(null),
        ]);
        if (!active) return;
        setReports(reportItems);
        setProducts(productItems.filter((item) => item.product_code === PRODUCT_CODE));
        setReportDate(initialDate);
        setSelected(detail);
      })
      .catch((caught) => { if (active) setError(String(caught)); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!renderJobs.some((job) => !isTerminal(job))) return;
    let canceled = false;
    const timer = window.setTimeout(() => {
      void Promise.all(renderJobs.map((job) => isTerminal(job) ? job : api.getJob(job.id)))
        .then(async (jobs) => {
          if (canceled) return;
          setRenderJobs(jobs);
          if (jobs.every(isTerminal) && selected?.id) await refreshReport(selected.id);
        })
        .catch((caught) => { if (!canceled) setError(String(caught)); });
    }, 1000);
    return () => { canceled = true; window.clearTimeout(timer); };
  }, [refreshReport, renderJobs, selected?.id]);

  useEffect(() => {
    if (outputsOpen) outputPanel.current?.focus();
  }, [outputsOpen]);

  async function flushPendingEdits(report = selected): Promise<Report | null> {
    const save = pendingSave.current;
    if (!save) return report;
    await save();
    pendingSave.current = null;
    if (!report) return null;
    return refreshReport(report.id);
  }

  async function run(work: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await work();
      if (selected?.id) await refreshReport(selected.id);
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  const productReports = useMemo(
    () => reportsForContext(reports, PRODUCT_CODE, reportDate)
      .filter((report) => report.lane === "PRODUCTION" && report.status !== "ARCHIVED")
      .sort((left, right) => (
        right.revision - left.revision
        || right.version - left.version
        || String(right.created_at ?? "").localeCompare(String(left.created_at ?? ""))
      )),
    [reports, reportDate],
  );
  const product = products.find((item) => item.product_code === PRODUCT_CODE);
  const artifacts = selected?.artifacts ?? [];
  const artifactsByFormat = useMemo(() => {
    const byFormat = new Map<OutputFormat, (typeof artifacts)[number]>();
    for (const artifact of artifacts) if (!byFormat.has(artifact.format)) byFormat.set(artifact.format, artifact);
    return byFormat;
  }, [artifacts]);
  const formatsToGenerate = selectedFormats.filter((format) => !artifactsByFormat.has(format));

  async function changeMonth(value: string) {
    if (!value) return;
    const nextDate = reportMonthEnd(value);
    if (nextDate === reportDate) return;
    setBusy(true);
    setError("");
    try {
      await flushPendingEdits();
      const [reportItems, productItems] = await Promise.all([api.listReports(), api.listProducts(nextDate)]);
      const next = selectReportForMonth(reportItems, PRODUCT_CODE, nextDate);
      const detail = next ? await api.getReport(next.id) : null;
      resetTransientState();
      setReports(reportItems);
      setProducts(productItems.filter((item) => item.product_code === PRODUCT_CODE));
      setReportDate(nextDate);
      setSelected(detail);
      setActiveModule("review");
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function changeReport(reportId: string) {
    if (!reportId || reportId === selected?.id) return;
    setBusy(true);
    setError("");
    try {
      await flushPendingEdits();
      const detail = await api.getReport(reportId);
      resetTransientState();
      setSelected(detail);
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function changeModule(moduleId: ModuleId) {
    if (moduleId === activeModule) return;
    setBusy(true);
    setError("");
    try {
      await flushPendingEdits();
      setActiveModule(moduleId);
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function createReport() {
    if (!product) return;
    setBusy(true);
    setError("");
    try {
      const created = await api.createReport(reportDate, PRODUCT_CODE);
      resetTransientState();
      await refreshReport(created.id);
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function openPreview() {
    if (!selected) return;
    const preview = window.open("about:blank", "_blank");
    if (!preview) {
      setError("Preview was blocked by the browser. Allow pop-ups for this application and try again.");
      return;
    }
    preview.opener = null;
    setBusy(true);
    setError("");
    try {
      const current = await flushPendingEdits(selected);
      if (!current) throw new Error("Report is no longer available.");
      preview.location.replace(`/api/v1/reports/${current.id}/preview`);
    } catch (caught) {
      preview.close();
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function reviewAndFinalize() {
    if (!selected || selected.status === "FINALIZED") return;
    setBusy(true);
    setError("");
    try {
      const current = await flushPendingEdits(selected);
      if (!current) throw new Error("Report is no longer available.");
      const verdict = await api.review(current.id);
      setReview(verdict);
      if (!verdict.ready) return;
      await api.finalize(current.id, current.latest_document?.version ?? 1);
      await refreshReport(current.id);
      setOutputsOpen(true);
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  function toggleFormat(format: OutputFormat) {
    setSelectedFormats((current) => current.includes(format)
      ? current.filter((item) => item !== format)
      : [...current, format]);
  }

  async function generateSelectedFormats() {
    if (!selected || selected.status !== "FINALIZED" || !formatsToGenerate.length) return;
    setBusy(true);
    setError("");
    try {
      const jobs = await api.render(selected.id, formatsToGenerate);
      setRenderJobs((current) => [
        ...current.filter((job) => !formatsToGenerate.includes(job.format)),
        ...jobs,
      ]);
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  const moduleStates = selected ? getModuleStates(selected) : {};

  return <div className="shell">
    <header className="topbar">
      <div className="brand"><span className="brand-rule" /><div><span className="eyebrow">REPORT AUTOMATION</span><h1>Monthly Commentary</h1></div></div>
      <div className="topbar-meta"><span>Canonical report workspace</span>{busy && <LoaderCircle className="spin" size={18} aria-label="Working" />}</div>
    </header>
    {error && <div className="error" role="alert">{error}</div>}
    <main className="app-main">
      <section className="report-context">
        <div className="fund-control">
          <label>Fund</label>
          <div className="fund-static" aria-label="Fund 3033"><strong>{product?.name_en ?? "CSOP Hang Seng TECH Index ETF"}</strong><span>3033</span></div>
          <p>{product ? `${product.ticker} · ${product.benchmark_name ?? product.benchmark_code} · ${product.currency}` : "3033.HK · Hang Seng TECH Index · HKD"}</p>
        </div>
        <div className="report-controls">
          <label>Report month<input type="month" value={reportDate.slice(0, 7)} onChange={(event) => void changeMonth(event.target.value)} disabled={busy} /></label>
          {selected && productReports.length > 0 && <label>Report version<select value={selected.id} onChange={(event) => void changeReport(event.target.value)} disabled={busy}>{productReports.map((report) => <option key={report.id} value={report.id}>{report.report_date} · r{report.revision} · {report.status}</option>)}</select></label>}
          {!selected && <button className="primary" disabled={busy || !product} onClick={() => void createReport()}><Plus size={17} /> Create report</button>}
          {selected && <>
            <button title="Open canonical preview" disabled={busy} onClick={() => void openPreview()}><Eye size={17} /> Preview</button>
            <button className="primary" disabled={busy || selected.status === "FINALIZED"} onClick={() => void reviewAndFinalize()}><FileCheck2 size={17} /> {selected.status === "FINALIZED" ? "Finalized" : "Review & finalize"}</button>
            <button disabled={busy || selected.status !== "FINALIZED"} onClick={() => setOutputsOpen(true)}><Download size={17} /> Downloads</button>
          </>}
        </div>
      </section>

      {!selected && !product && <div className="month-unavailable" role="status"><AlertTriangle size={18} /><span>Fund 3033 is not available for the selected report month. Choose a month within the product's effective dates.</span></div>}

      {!selected && product && <section className="no-report">
        <span className="empty-number">{reportDate.slice(0, 7)}</span>
        <div><span className="eyebrow">NEW MONTHLY COMMENTARY</span><h2>No report for this month yet</h2><p>Create the report here; the selected month will be stored as {reportDate}, and no separate date-selection page is required.</p></div>
      </section>}

      {selected && <>
        <section className="status-rail">
          <div>
            <span className={`status ${selected.status.toLowerCase()}`}>{selected.status}</span>
            {selected.lane === "TESTING" && <span className="lane-chip" title="Bound to testing data. Artifacts are watermarked and named TESTING-…"><AlertTriangle size={13} aria-hidden="true" /> TESTING DATA</span>}
            <small>Report lifecycle</small>
          </div>
          <div><span>Snapshot</span><strong>{selected.active_snapshot_id ? "Bound" : "Missing"}</strong></div>
          <div><span>Quality</span><strong>{selected.quality_results?.filter((item) => item.status === "PASSED").length ?? 0}/{selected.quality_results?.length ?? 0}</strong></div>
          <div><span>Artifacts</span><strong>{artifactsByFormat.size}</strong></div>
        </section>

        {review && <section className={`review-result ${review.ready ? "ready" : "blocked"}`}>
          <div>{review.ready ? <CheckCircle2 size={22} /> : <AlertTriangle size={22} />}<div><strong>{review.ready ? (selected.status === "FINALIZED" ? "Review passed and report finalized" : "Review passed; finalization is in progress") : `${review.blocking.length} blocking checks`}</strong><span>{review.ready ? `${review.warnings.length} unresolved warning${review.warnings.length === 1 ? "" : "s"}.` : review.blocking.map((item) => `${item.check_id}: ${item.fix_hint}`).join(" · ")}</span></div></div>
        </section>}

        {selected.status === "FINALIZED" && outputsOpen && <section className="artifact-panel" ref={outputPanel} tabIndex={-1}>
          <header><div><strong>Report outputs</strong><span>Select one or more formats. Existing finalized artifacts are reused.</span></div></header>
          <div className="output-controls">
            <div className="format-selector" role="group" aria-label="Output formats">
              {OUTPUT_FORMATS.map(({ value, label }) => <label key={value}><input type="checkbox" checked={selectedFormats.includes(value)} onChange={() => toggleFormat(value)} /> <span>{label}</span></label>)}
            </div>
            <button className="primary" disabled={busy || !selectedFormats.length || !formatsToGenerate.length} onClick={() => void generateSelectedFormats()}><FileOutput size={16} /> {formatsToGenerate.length ? "Generate selected" : "Selected outputs ready"}</button>
          </div>
          {renderJobs.length > 0 && <div className="render-jobs">{renderJobs.map((job) => <div key={job.id}><span>{formatLabel(job.format)}</span><strong>{job.status}</strong>{job.error?.message && <small>{job.error.message}</small>}</div>)}</div>}
          <div className="artifact-list">{OUTPUT_FORMATS.flatMap(({ value, label }) => {
            const artifact = artifactsByFormat.get(value);
            return artifact ? [<article key={artifact.id}><div><strong>{label}</strong><span>{new Intl.NumberFormat("en-HK").format(artifact.size_bytes)} bytes · {artifact.checksum.slice(0, 12)}</span></div><button title={`Download ${label}`} onClick={() => run(() => api.downloadArtifact(artifact.id))}><Download size={17} /> Download {label}</button></article>] : [];
          })}</div>
        </section>}

        <div className="workbench"><ModuleNav active={activeModule} onSelect={(moduleId) => void changeModule(moduleId)} states={moduleStates} /><section className="module-stage"><ReportModule report={selected} active={activeModule} busy={busy} run={run} registerPendingSave={registerPendingSave} /></section></div>
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
    footnotes: FOOTNOTE_SECTIONS.every(({ key }) => typeof footnotes[key] === "string" && (footnotes[key] as string).trim()) ? "ready" : "attention",
  };
}

export default App;
