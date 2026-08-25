import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ChevronDown, Download, Eye, FileCheck2, LoaderCircle, Plus, Trash2 } from "lucide-react";
import { api, type OutputFormat, type Product, type RenderJob, type Report } from "./api";
import { type ModuleId, ModuleNav } from "./components/ModuleNav";
import { ReportModule } from "./components/ReportModulesV2";
import type { PendingSave, RegisterPendingSave } from "./pendingSave";
import { FOOTNOTE_SECTIONS, reportsForContext, reviewHasContent, selectInitialReport, selectReportForMonth } from "./reportModules";
import { useLocale, type Locale } from "./i18n";
import "./styles.css";

const PRODUCT_CODE = "3033";
const OUTPUT_FORMATS: Array<{ value: OutputFormat; label: string }> = [
  { value: "pdf", label: "PDF" },
  { value: "html", label: "HTML" },
  { value: "docx", label: "Word (.docx)" },
];
const MONTH_OPTIONS = Array.from({ length: 12 }, (_, index) => String(index + 1).padStart(2, "0"));

function reportMonthEnd(value: string): string {
  const [year, month] = value.split("-").map(Number);
  if (!Number.isInteger(year) || !Number.isInteger(month) || year < 1000 || month < 1 || month > 12) {
    throw new Error("Enter a valid four-digit report year and month.");
  }
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

function isTerminal(job: RenderJob): boolean {
  return ["SUCCEEDED", "FAILED", "CANCELED"].includes(job.status);
}

function sectionRows(report: Report, section: "historical_performance" | "constituents"): unknown[] {
  const sections = report.latest_document?.content.sections;
  if (!sections || typeof sections !== "object") return [];
  const value = (sections as Record<string, unknown>)[section];
  if (section === "constituents") return Array.isArray(value) ? value : [];
  if (!value || typeof value !== "object") return [];
  const rows = (value as Record<string, unknown>).rows;
  return Array.isArray(rows) ? rows : [];
}

export function needsAutomaticBackfill(report: Report): boolean {
  const constituentsReady = sectionRows(report, "constituents").length > 0;
  const sections = report.latest_document?.content.sections;
  const analytics = sections && typeof sections === "object"
    ? (sections as Record<string, unknown>).analytics
    : null;
  const top10 = analytics && typeof analytics === "object"
    ? (analytics as Record<string, unknown>).top10
    : null;
  const portfolio = analytics && typeof analytics === "object"
    ? (analytics as Record<string, unknown>).portfolio
    : null;
  const portfolioCodes = new Set(
    (Array.isArray(portfolio) ? portfolio : [])
      .filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === "object")
      .map((row) => String(row.metric_code ?? "")),
  );
  const portfolioLabels = new Set(
    (Array.isArray(portfolio) ? portfolio : [])
      .filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === "object")
      .map((row) => String(row.label ?? "")),
  );
  const hasPortfolioMetric = (code: string, label: string) => (
    portfolioCodes.has(code) || portfolioLabels.has(label)
  );
  const hasAum = (
    hasPortfolioMetric("AUM", "Asset Under Management")
    || [...portfolioLabels].some((label) => label.startsWith("Asset Under Management ("))
  );
  const hasTurnover = (
    hasPortfolioMetric("AVERAGE_DAILY_TURNOVER", "Average Daily Turnover")
    || [...portfolioLabels].some((label) => label.startsWith("Average Daily Turnover ("))
  );
  const hasHoldings = hasPortfolioMetric("NUMBER_OF_HOLDINGS", "Number of holdings");
  const portfolioMissing = constituentsReady && (!hasAum || !hasTurnover || !hasHoldings);
  const finalAnalyticsMissing = constituentsReady
    && ((!Array.isArray(top10) || top10.length === 0) || portfolioMissing);
  const sourceDataMissing = report.status === "DRAFT"
    && (!sectionRows(report, "historical_performance").length || !constituentsReady);
  return report.status !== "FINALIZED" && report.status !== "ARCHIVED"
    && (sourceDataMissing || finalAnalyticsMissing);
}

function App() {
  const { locale, languageMode, setLocale, t, statusLabel } = useLocale();
  const [products, setProducts] = useState<Product[]>([]);
  const [reports, setReports] = useState<Report[]>([]);
  const [selected, setSelected] = useState<Report | null>(null);
  const [reportDate, setReportDate] = useState(currentHongKongMonthEnd);
  const [reportYearInput, setReportYearInput] = useState(() => currentHongKongMonthEnd().slice(0, 4));
  const [activeModule, setActiveModule] = useState<ModuleId>("review");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [downloadsOpen, setDownloadsOpen] = useState(false);
  const [downloadingFormat, setDownloadingFormat] = useState<OutputFormat | null>(null);
  const pendingSave = useRef<PendingSave | null>(null);

  const registerPendingSave = useCallback<RegisterPendingSave>((save) => {
    pendingSave.current = save;
  }, []);

  const resetTransientState = useCallback(() => {
    pendingSave.current = null;
    setDownloadsOpen(false);
    setDownloadingFormat(null);
  }, []);

  const refreshReport = useCallback(async (reportId: string): Promise<Report> => {
    const [nextReports, detail] = await Promise.all([api.listReports(), api.getReport(reportId)]);
    setReports(nextReports);
    setSelected(detail);
    return detail;
  }, []);

  const loadSelectedReport = useCallback(async (reportId: string): Promise<Report> => {
    let detail = await api.getReport(reportId);
    if (needsAutomaticBackfill(detail)) {
      await api.refreshAutomaticData(detail.id, detail.version);
      detail = await api.getReport(reportId);
    }
    return detail;
  }, []);

  useEffect(() => {
    let active = true;
    void api.listReports()
      .then(async (reportItems) => {
        const initial = selectInitialReport(reportItems, PRODUCT_CODE, languageMode);
        const initialDate = initial?.report_date ?? currentHongKongMonthEnd();
        const [productItems, detail] = await Promise.all([
          api.listProducts(initialDate),
          initial ? loadSelectedReport(initial.id) : Promise.resolve(null),
        ]);
        if (!active) return;
        setReports(reportItems);
        setProducts(productItems.filter((item) => item.product_code === PRODUCT_CODE));
        setReportDate(initialDate);
        setSelected(detail);
      })
      .catch((caught) => { if (active) setError(String(caught)); });
    return () => { active = false; };
  }, [loadSelectedReport]);

  useEffect(() => {
    setReportYearInput(reportDate.slice(0, 4));
  }, [reportDate]);

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
      .filter((report) => (report.language_mode ?? "EN") === languageMode && report.lane === "PRODUCTION" && report.status !== "ARCHIVED")
      .sort((left, right) => (
        right.revision - left.revision
        || right.version - left.version
        || String(right.created_at ?? "").localeCompare(String(left.created_at ?? ""))
      )),
    [reports, reportDate, languageMode],
  );
  const product = products.find((item) => item.product_code === PRODUCT_CODE);
  const artifacts = selected?.artifacts ?? [];
  const artifactsByFormat = useMemo(() => {
    const byFormat = new Map<OutputFormat, (typeof artifacts)[number]>();
    for (const artifact of artifacts) if (artifact.is_current !== false && !byFormat.has(artifact.format)) byFormat.set(artifact.format, artifact);
    return byFormat;
  }, [artifacts]);

  async function changeMonth(value: string) {
    if (!value) return;
    let nextDate: string;
    try {
      nextDate = reportMonthEnd(value);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      return;
    }
    if (nextDate === reportDate) return;
    setBusy(true);
    setError("");
    try {
      await flushPendingEdits();
      const [reportItems, productItems] = await Promise.all([api.listReports(), api.listProducts(nextDate)]);
      const next = selectReportForMonth(reportItems, PRODUCT_CODE, nextDate, languageMode);
      const detail = next ? await loadSelectedReport(next.id) : null;
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

  async function changeReportPeriod(year: string, month: string) {
    if (!/^\d{4}$/.test(year) || !MONTH_OPTIONS.includes(month)) {
      setError(t("invalidPeriod"));
      return;
    }
    await changeMonth(`${year}-${month}`);
  }

  async function changeLanguage(nextLocale: Locale) {
    if (nextLocale === locale) return;
    const nextLanguageMode = nextLocale === "zh-Hans" ? "ZH_HANS" : "EN";
    setBusy(true);
    setError("");
    try {
      await flushPendingEdits();
      const reportItems = await api.listReports();
      const next = selectReportForMonth(reportItems, PRODUCT_CODE, reportDate, nextLanguageMode);
      const detail = next ? await loadSelectedReport(next.id) : null;
      resetTransientState();
      setReports(reportItems);
      setSelected(detail);
      setActiveModule("review");
      setLocale(nextLocale);
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  function changeReportYear(value: string) {
    const normalized = value.replace(/\D/g, "").slice(0, 4);
    setReportYearInput(normalized);
    if (normalized.length === 4) void changeReportPeriod(normalized, reportDate.slice(5, 7));
  }

  async function changeReport(reportId: string) {
    if (!reportId || reportId === selected?.id) return;
    setBusy(true);
    setError("");
    try {
      await flushPendingEdits();
      const detail = await loadSelectedReport(reportId);
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

  async function createReport(createFresh = false) {
    if (!product) return;
    setBusy(true);
    setError("");
    try {
      await flushPendingEdits();
      const source = createFresh ? undefined : reportsForContext(reports, PRODUCT_CODE, reportDate)
        .filter((report) => (report.language_mode ?? "EN") !== languageMode && report.status !== "ARCHIVED")
        .sort((left, right) => right.version - left.version)[0];
      const created = source
        ? await api.createLanguageVariant(source.id, languageMode, source.latest_document?.version ?? (await api.getReport(source.id)).latest_document?.version ?? 1)
        : locale === "zh-Hans"
          ? await api.createReport(reportDate, PRODUCT_CODE, languageMode)
          : await api.createReport(reportDate, PRODUCT_CODE);
      resetTransientState();
      await refreshReport(created.id);
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function deleteReport() {
    if (!selected) return;
    const confirmed = window.confirm(
      t("deleteConfirm", { date: selected.report_date, revision: selected.revision, status: statusLabel(selected.status) }),
    );
    if (!confirmed) return;

    setBusy(true);
    setError("");
    try {
      const current = await flushPendingEdits(selected);
      if (!current) throw new Error(t("unavailable"));
      await api.deleteReport(current.id, current.version);
      const reportItems = await api.listReports();
      const next = selectReportForMonth(reportItems, PRODUCT_CODE, reportDate, languageMode);
      const detail = next ? await loadSelectedReport(next.id) : null;
      resetTransientState();
      setReports(reportItems);
      setSelected(detail);
      setActiveModule("review");
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
      setError(t("popupBlocked"));
      return;
    }
    preview.opener = null;
    setBusy(true);
    setError("");
    try {
      const current = await flushPendingEdits(selected);
      if (!current) throw new Error(t("unavailable"));
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
      if (!current) throw new Error(t("unavailable"));
      await api.finalize(current.id, current.latest_document?.version ?? 1);
      await refreshReport(current.id);
      setDownloadsOpen(true);
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function downloadOutput(format: OutputFormat) {
    if (!selected || selected.status !== "FINALIZED") return;
    const reportId = selected.id;
    setDownloadsOpen(false);
    setDownloadingFormat(format);
    setBusy(true);
    setError("");
    try {
      const existing = artifactsByFormat.get(format);
      if (existing) {
        await api.downloadArtifact(existing.id);
        return;
      }
      const jobs = await api.render(reportId, [format]);
      let job = jobs.find((item) => item.format === format);
      if (!job) throw new Error(`The ${format.toUpperCase()} render job was not created.`);
      while (!isTerminal(job)) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        job = await api.getJob(job.id);
      }
      if (job.status !== "SUCCEEDED" || !job.artifact_id) {
        throw new Error(job.error?.message ?? `The ${format.toUpperCase()} download could not be generated.`);
      }
      await api.downloadArtifact(job.artifact_id);
      await refreshReport(reportId);
    } catch (caught) {
      setError(String(caught));
    } finally {
      setDownloadingFormat(null);
      setBusy(false);
    }
  }

  const moduleStates = selected ? getModuleStates(selected) : {};

  return <div className="shell">
    <header className="topbar">
      <div className="brand"><span className="brand-rule" /><div><span className="eyebrow">{t("brandEyebrow")}</span><h1>{t("appName")}</h1></div></div>
      <div className="topbar-meta"><span>{t("workspace")}</span><label className="language-picker"><span>{t("language")}</span><select aria-label={t("language")} value={locale} disabled={busy} onChange={(event) => void changeLanguage(event.target.value as Locale)}><option value="en">English</option><option value="zh-Hans">简体中文</option></select></label>{busy && <LoaderCircle className="spin" size={18} aria-label={t("working")} />}</div>
    </header>
    {error && <div className="error" role="alert">{error}</div>}
    <main className="app-main">
      <section className="report-context">
        <div className="fund-control">
          <label>{t("fund")}</label>
          <div className="fund-static" aria-label={`${t("fund")} 3033`}><strong>{locale === "zh-Hans" ? (selected?.product_name || product?.name_zh_hans || product?.ticker || "3033") : (product?.name_en ?? "CSOP Hang Seng TECH Index ETF")}</strong><span>3033</span></div>
          <p>{product ? `${product.ticker} · ${locale === "zh-Hans" ? product.benchmark_code : (product.benchmark_name ?? product.benchmark_code)} · ${product.currency}` : `3033.HK · ${locale === "zh-Hans" ? "HSTECH" : "Hang Seng TECH Index"} · HKD`}</p>
        </div>
        <div className="report-controls">
          <label>{t("reportYear")}<input type="number" inputMode="numeric" min="1000" max="9999" step="1" value={reportYearInput} onChange={(event) => changeReportYear(event.target.value)} onBlur={() => { if (!/^\d{4}$/.test(reportYearInput)) setError(t("invalidYear")); }} disabled={busy} /></label>
          <label>{t("reportMonth")}<select value={reportDate.slice(5, 7)} onChange={(event) => void changeReportPeriod(reportYearInput, event.target.value)} disabled={busy || !/^\d{4}$/.test(reportYearInput)}>{MONTH_OPTIONS.map((month) => <option key={month} value={month}>{new Intl.DateTimeFormat(locale === "zh-Hans" ? "zh-CN" : "en", { month: "long", timeZone: "UTC" }).format(new Date(`2024-${month}-01T00:00:00Z`))}</option>)}</select></label>
          {selected && productReports.length > 0 && <label>{t("reportVersion")}<select value={selected.id} onChange={(event) => void changeReport(event.target.value)} disabled={busy}>{productReports.map((report) => <option key={report.id} value={report.id}>{report.report_date} · r{report.revision} · {statusLabel(report.status)}</option>)}</select></label>}
          {!selected && <button className="primary" disabled={busy || !product} onClick={() => void createReport()}><Plus size={17} /> {reportsForContext(reports, PRODUCT_CODE, reportDate).some((report) => report.language_mode !== languageMode) ? t("createLanguageVersion", { language: locale === "zh-Hans" ? t("simplifiedChinese") : t("english") }) : t("createReport")}</button>}
          {selected && <>
            <button disabled={busy || !product} onClick={() => void createReport(true)}><Plus size={17} /> {t("newReport")}</button>
            <button className="danger-button" disabled={busy} onClick={() => void deleteReport()}><Trash2 size={17} /> {t("deleteReport")}</button>
            <button title={t("preview")} disabled={busy} onClick={() => void openPreview()}><Eye size={17} /> {t("preview")}</button>
            <button className="primary" disabled={busy || selected.status === "FINALIZED"} onClick={() => void reviewAndFinalize()}><FileCheck2 size={17} /> {selected.status === "FINALIZED" ? t("finalized") : t("finalize")}</button>
            <div className="download-dropdown">
              <button
                disabled={busy || selected.status !== "FINALIZED"}
                aria-haspopup="menu"
                aria-expanded={downloadsOpen}
                onClick={() => setDownloadsOpen((open) => !open)}
              ><Download size={17} /> {t("downloads")} <ChevronDown size={15} /></button>
              {downloadsOpen && selected.status === "FINALIZED" && <div className="download-menu popover" role="menu" aria-label={t("downloadReport")}>
                {OUTPUT_FORMATS.map(({ value, label }) => <button key={value} role="menuitem" onClick={() => void downloadOutput(value)}>
                  <Download size={16} />
                  <span><strong>{label}</strong><small>{artifactsByFormat.has(value) ? t("readyDownload") : t("generateDownload")}</small></span>
                </button>)}
              </div>}
            </div>
          </>}
        </div>
      </section>

      {!selected && !product && <div className="month-unavailable" role="status"><AlertTriangle size={18} /><span>{t("productUnavailable")}</span></div>}

      {!selected && product && <section className="no-report">
        <span className="empty-number">{reportDate.slice(0, 7)}</span>
        <div><span className="eyebrow">{t("newMonthlyCommentary")}</span><h2>{t("noReport", { language: locale === "zh-Hans" ? t("simplifiedChinese") : t("english") })}</h2><p>{t("noReportHelp", { language: locale === "zh-Hans" ? t("simplifiedChinese") : t("english"), date: reportDate })}</p></div>
      </section>}

      {selected && <>
        <section className="status-rail">
          <div>
            <span className={`status ${selected.status.toLowerCase()}`}>{statusLabel(selected.status)}</span>
            {selected.lane === "TESTING" && <span className="lane-chip" title={t("testingHelp")}><AlertTriangle size={13} aria-hidden="true" /> {t("testingData")}</span>}
            <small>{t("lifecycle")}</small>
          </div>
          <div><span>{t("snapshot")}</span><strong>{selected.active_snapshot_id ? t("bound") : t("missing")}</strong></div>
          <div><span>{t("quality")}</span><strong>{selected.quality_results?.filter((item) => item.status === "PASSED").length ?? 0}/{selected.quality_results?.length ?? 0}</strong></div>
          <div><span>{t("artifacts")}</span><strong>{artifactsByFormat.size}</strong></div>
        </section>

        {downloadingFormat && <div className="download-progress" role="status">{t("preparing", { format: OUTPUT_FORMATS.find((item) => item.value === downloadingFormat)?.label ?? downloadingFormat })}</div>}

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
  const reviewReady = reviewHasContent(review);
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
