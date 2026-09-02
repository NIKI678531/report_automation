import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createBrowserRouter, RouterProvider, useBlocker, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { AlertTriangle, Archive, ArrowLeft, CalendarDays, ChevronDown, Download, Eye, FileCheck2, FileText, Home, LoaderCircle, Plus, Trash2 } from "lucide-react";
import { api, type OutputFormat, type Product, type RenderJob, type Report, type ReportLanguage } from "./api";
import { type ModuleId, ModuleNav } from "./components/ModuleNav";
import { ReportModule } from "./components/ReportModulesV2";
import type { PendingSave, RegisterPendingSave } from "./pendingSave";
import { FOOTNOTE_SECTIONS, isReportReadOnly, reportsForContext, reviewHasContent, selectReportForMonth } from "./reportModules";
import { useLocale, type Locale } from "./i18n";
import "./styles.css";

const PRODUCT_CODE = "3033";
const OUTPUT_FORMATS: Array<{ value: OutputFormat; label: string }> = [
  { value: "pdf", label: "PDF" },
  { value: "html", label: "HTML" },
  { value: "docx", label: "Word (.docx)" },
];
const MONTH_OPTIONS = Array.from({ length: 12 }, (_, index) => String(index + 1).padStart(2, "0"));

export function reportMonthEnd(value: string): string {
  const [year, month] = value.split("-").map(Number);
  if (!Number.isInteger(year) || !Number.isInteger(month) || year < 1000 || month < 1 || month > 12) {
    throw new Error("Enter a valid four-digit report year and month.");
  }
  const day = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return `${value}-${String(day).padStart(2, "0")}`;
}

export function currentHongKongMonthEnd(): string {
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

function languageLabel(language: ReportLanguage, t: ReturnType<typeof useLocale>["t"]): string {
  if (language === "ZH_HANS") return t("simplifiedChinese");
  if (language === "ZH_HANT") return t("traditionalChinese");
  if (language === "BILINGUAL") return t("bilingual");
  return t("english");
}

function AppHeader({ busy = false, onLanguageChange }: { busy?: boolean; onLanguageChange?: (locale: Locale) => void }) {
  const { locale, setLocale, t } = useLocale();
  return <header className="topbar">
    <div className="brand"><span className="brand-rule" /><div><span className="eyebrow">{t("brandEyebrow")}</span><h1>{t("appName")}</h1></div></div>
    <div className="topbar-meta"><span>{t("workspace")}</span><label className="language-picker"><span>{t("language")}</span><select aria-label={t("language")} value={locale} disabled={busy} onChange={(event) => (onLanguageChange ?? setLocale)(event.target.value as Locale)}><option value="en">English</option><option value="zh-Hans">简体中文</option><option value="zh-Hant">繁體中文</option></select></label>{busy && <LoaderCircle className="spin" size={18} aria-label={t("working")} />}</div>
  </header>;
}

function groupedByMonth(items: Report[]): Array<[string, Report[]]> {
  const groups = new Map<string, Report[]>();
  for (const report of items) {
    const month = report.report_date.slice(0, 7);
    groups.set(month, [...(groups.get(month) ?? []), report]);
  }
  return [...groups.entries()]
    .sort(([left], [right]) => right.localeCompare(left))
    .map(([month, reports]) => [month, reports.sort((left, right) => (
      String(right.updated_at ?? right.created_at ?? "").localeCompare(String(left.updated_at ?? left.created_at ?? ""))
      || right.revision - left.revision
      || right.version - left.version
    ))]);
}

function ReportGroups({ reports }: { reports: Report[] }) {
  const navigate = useNavigate();
  const { locale, formatDate, formatMonth, statusLabel, t } = useLocale();
  const dateTimeLocale = locale === "zh-Hans" ? "zh-CN" : locale === "zh-Hant" ? "zh-HK" : "en-GB";
  return <div className="report-month-groups stagger">
    {groupedByMonth(reports).map(([month, monthReports]) => <section className="report-month-card" key={month}>
      <header><div><span className="eyebrow">{t("reportMonth")}</span><h3>{formatMonth(`${month}-01`)}</h3></div><span className="report-count">{t("reportCount", { count: monthReports.length })}</span></header>
      <div className="report-records">
        {monthReports.map((report) => <button className="report-record" key={report.id} aria-label={t("openReport", { date: report.report_date, language: languageLabel(report.language_mode, t), status: statusLabel(report.status) })} onClick={() => navigate(`/reports/${report.id}`)}>
          <span className={`status ${report.status.toLowerCase()}`}>{statusLabel(report.status)}</span>
          <span className="report-record-main"><strong>{languageLabel(report.language_mode, t)}</strong><small>{formatDate(report.report_date)} · {t("revision", { revision: report.revision })}</small></span>
          <span className="report-record-updated"><small>{t("lastUpdated")}</small><time dateTime={report.updated_at}>{report.updated_at ? new Intl.DateTimeFormat(dateTimeLocale, { dateStyle: "medium", timeStyle: "short" }).format(new Date(report.updated_at)) : t("notAvailable")}</time></span>
          <FileText size={18} aria-hidden="true" />
        </button>)}
      </div>
    </section>)}
  </div>;
}

function ReportsHome() {
  const navigate = useNavigate();
  const { t } = useLocale();
  const [reports, setReports] = useState<Report[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void api.listReports({ includeArchived: true })
      .then((items) => { if (active) setReports(items.filter((item) => item.product_code === PRODUCT_CODE)); })
      .catch((caught) => { if (active) setError(String(caught)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const current = reports.filter((report) => report.status !== "ARCHIVED");
  const archived = reports.filter((report) => report.status === "ARCHIVED");
  return <div className="shell">
    <AppHeader />
    {error && <div className="error" role="alert">{error}</div>}
    <main className="app-main report-center">
      <section className="report-center-hero">
        <div><span className="eyebrow">{t("reportLibrary")}</span><h2>{t("reportCenter")}</h2><p>{t("reportCenterHelp")}</p></div>
        <button className="primary report-center-cta" onClick={() => navigate("/reports/new")}><Plus size={18} /> {t("newReport")}</button>
      </section>
      {loading ? <div className="report-center-loading" role="status" aria-label={t("loadingReports")}><span /><span /><span /></div> : current.length ? <ReportGroups reports={current} /> : <section className="report-center-empty"><CalendarDays size={28} /><h3>{t("noReportsYet")}</h3><p>{t("noReportsYetHelp")}</p></section>}
      {archived.length > 0 && <details className="archive-section">
        <summary><span><Archive size={18} /> {t("archivedReports")}</span><small>{t("reportCount", { count: archived.length })}</small></summary>
        <ReportGroups reports={archived} />
      </details>}
    </main>
  </div>;
}

function NewReportPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { locale, languageMode, setLocale, t, statusLabel } = useLocale();
  const initialMonth = /^\d{4}-\d{2}$/.test(searchParams.get("month") ?? "") ? searchParams.get("month")! : currentHongKongMonthEnd().slice(0, 7);
  const [year, setYear] = useState(initialMonth.slice(0, 4));
  const [month, setMonth] = useState(initialMonth.slice(5, 7));
  const [reportLanguage, setReportLanguage] = useState<Extract<ReportLanguage, "EN" | "ZH_HANS" | "ZH_HANT">>(() => {
    const requested = searchParams.get("language");
    return requested === "EN" || requested === "ZH_HANS" || requested === "ZH_HANT" ? requested : languageMode;
  });
  const [reports, setReports] = useState<Report[]>([]);
  const [product, setProduct] = useState<Product | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const validPeriod = /^\d{4}$/.test(year) && MONTH_OPTIONS.includes(month);
  const reportDate = validPeriod ? reportMonthEnd(`${year}-${month}`) : "";

  useEffect(() => {
    let active = true;
    setLoading(true);
    const products = reportDate ? api.listProducts(reportDate) : Promise.resolve([]);
    void Promise.all([api.listReports({ includeArchived: true }), products])
      .then(([items, productItems]) => {
        if (!active) return;
        setReports(items.filter((item) => item.product_code === PRODUCT_CODE));
        setProduct(productItems.find((item) => item.product_code === PRODUCT_CODE) ?? null);
        setError("");
      })
      .catch((caught) => { if (active) setError(String(caught)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reportDate]);

  const matches = reportDate ? reportsForContext(reports, PRODUCT_CODE, reportDate)
    .filter((report) => report.language_mode === reportLanguage) : [];

  async function submit() {
    if (!reportDate || !product) return;
    setBusy(true);
    setError("");
    try {
      const created = await api.createReport(reportDate, PRODUCT_CODE, reportLanguage);
      navigate(`/reports/${created.id}`, { replace: true });
    } catch (caught) {
      setError(String(caught));
      setBusy(false);
    }
  }

  return <div className="shell">
    <AppHeader busy={busy || loading} onLanguageChange={(next) => { setLocale(next); setReportLanguage(next === "zh-Hans" ? "ZH_HANS" : next === "zh-Hant" ? "ZH_HANT" : "EN"); }} />
    {error && <div className="error" role="alert">{error}</div>}
    <main className="app-main new-report-page">
      <button className="quiet-button back-button" onClick={() => navigate("/")}><ArrowLeft size={17} /> {t("backToReports")}</button>
      <section className="new-report-hero">
        <span className="eyebrow">{t("newMonthlyCommentary")}</span>
        <h2>{t("createNewReport")}</h2>
        <p>{t("createNewReportHelp")}</p>
      </section>
      <section className="new-report-form">
        <div className="fund-control"><label>{t("fund")}</label><div className="fund-static" aria-label={`${t("fund")} 3033`}><strong>{product?.name_en ?? "CSOP Hang Seng TECH Index ETF"}</strong><span>3033</span></div><p>{product ? `${product.ticker} · ${product.benchmark_name ?? product.benchmark_code} · ${product.currency}` : "3033.HK · Hang Seng TECH Index · HKD"}</p></div>
        <div className="new-report-fields">
          <label>{t("reportYear")}<input aria-label={t("reportYear")} type="number" inputMode="numeric" min="1000" max="9999" value={year} onChange={(event) => setYear(event.target.value.replace(/\D/g, "").slice(0, 4))} /></label>
          <label>{t("reportMonth")}<select aria-label={t("reportMonth")} value={month} onChange={(event) => setMonth(event.target.value)}>{MONTH_OPTIONS.map((value) => <option key={value} value={value}>{new Intl.DateTimeFormat(locale === "zh-Hans" ? "zh-CN" : locale === "zh-Hant" ? "zh-HK" : "en", { month: "long", timeZone: "UTC" }).format(new Date(`2024-${value}-01T00:00:00Z`))}</option>)}</select></label>
          <label>{t("reportLanguage")}<select aria-label={t("reportLanguage")} value={reportLanguage} onChange={(event) => setReportLanguage(event.target.value as typeof reportLanguage)}><option value="EN">{t("english")}</option><option value="ZH_HANS">{t("simplifiedChinese")}</option><option value="ZH_HANT">{t("traditionalChinese")}</option></select></label>
        </div>
        {!loading && !product && <div className="month-unavailable" role="status"><AlertTriangle size={18} /><span>{t("productUnavailable")}</span></div>}
        {matches.length > 0 && <section className="duplicate-report-notice" role="status"><AlertTriangle size={18} /><div><strong>{t("existingReportsFound")}</strong><p>{t("existingReportsHelp")}</p><ul>{matches.map((report) => <li key={report.id}>{report.report_date} · {statusLabel(report.status)} · {t("revision", { revision: report.revision })}</li>)}</ul></div></section>}
        <div className="new-report-actions"><button onClick={() => navigate("/")}>{t("cancel")}</button><button className="primary" disabled={busy || loading || !validPeriod || !product} onClick={() => void submit()}>{busy ? <LoaderCircle className="spin" size={17} /> : <Plus size={17} />} {matches.length ? t("createAnotherReport") : t("createReport")}</button></div>
      </section>
    </main>
  </div>;
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

function ReportWorkspace() {
  const { reportId = "" } = useParams();
  const navigate = useNavigate();
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
  const [loading, setLoading] = useState(true);
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
    const [nextReports, detail] = await Promise.all([api.listReports({ includeArchived: true }), api.getReport(reportId)]);
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
    setLoading(true);
    setError("");
    void Promise.all([api.listReports({ includeArchived: true }), loadSelectedReport(reportId)])
      .then(async ([reportItems, detail]) => {
        const productItems = await api.listProducts(detail.report_date);
        if (!active) return;
        setReports(reportItems);
        setProducts(productItems.filter((item) => item.product_code === PRODUCT_CODE));
        setReportDate(detail.report_date);
        setSelected(detail);
      })
      .catch((caught) => { if (active) { setSelected(null); setError(String(caught)); } })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [loadSelectedReport, reportId]);

  useEffect(() => {
    setReportYearInput(reportDate.slice(0, 4));
  }, [reportDate]);

  const flushPendingEdits = useCallback(async (report = selected): Promise<Report | null> => {
    const save = pendingSave.current;
    if (!save) return report;
    await save();
    pendingSave.current = null;
    if (!report) return null;
    return refreshReport(report.id);
  }, [refreshReport, selected]);

  const blocker = useBlocker(({ currentLocation, nextLocation }) => (
    pendingSave.current !== null && currentLocation.pathname !== nextLocation.pathname
  ));

  useEffect(() => {
    if (blocker.state !== "blocked") return;
    setBusy(true);
    setError("");
    void flushPendingEdits()
      .then(() => blocker.proceed())
      .catch((caught) => { setError(String(caught)); blocker.reset(); })
      .finally(() => setBusy(false));
  }, [blocker, flushPendingEdits]);

  useEffect(() => {
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!pendingSave.current) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, []);

  async function navigateAfterSave(path: string) {
    setBusy(true);
    setError("");
    try {
      await flushPendingEdits();
      navigate(path);
    } catch (caught) {
      setError(String(caught));
      setBusy(false);
    }
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
      .filter((report) => (
        (report.language_mode ?? "EN") === languageMode
        && report.lane === "PRODUCTION"
        && (selected?.status === "ARCHIVED" ? report.status === "ARCHIVED" : report.status !== "ARCHIVED")
      ))
      .sort((left, right) => (
        right.revision - left.revision
        || right.version - left.version
        || String(right.created_at ?? "").localeCompare(String(left.created_at ?? ""))
      )),
    [reports, reportDate, languageMode, selected?.status],
  );
  const product = products.find((item) => item.product_code === PRODUCT_CODE);
  const artifacts = selected?.artifacts ?? [];
  const artifactsByFormat = useMemo(() => {
    const byFormat = new Map<OutputFormat, (typeof artifacts)[number]>();
    for (const artifact of artifacts) {
      const downloadable = selected?.status === "ARCHIVED" || artifact.is_current !== false;
      if (downloadable && !byFormat.has(artifact.format)) byFormat.set(artifact.format, artifact);
    }
    return byFormat;
  }, [artifacts, selected?.status]);

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
      const reportItems = await api.listReports();
      const next = selectReportForMonth(reportItems, PRODUCT_CODE, nextDate, languageMode);
      resetTransientState();
      navigate(next ? `/reports/${next.id}` : `/reports/new?month=${nextDate.slice(0, 7)}&language=${languageMode}`);
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
    const nextLanguageMode = nextLocale === "zh-Hans" ? "ZH_HANS" : nextLocale === "zh-Hant" ? "ZH_HANT" : "EN";
    if (selected?.status === "ARCHIVED") {
      const next = reportsForContext(reports, PRODUCT_CODE, reportDate)
        .filter((report) => (
          report.status === "ARCHIVED"
          && report.language_mode === nextLanguageMode
          && report.revision === selected.revision
        ))
        .sort((left, right) => right.version - left.version)[0];
      setLocale(nextLocale);
      if (next) navigate("/reports/" + next.id, { replace: true });
      return;
    }
    setBusy(true);
    setError("");
    try {
      const current = await flushPendingEdits();
      let reportItems = await api.listReports();
      let next = current
        ? reportsForContext(reportItems, PRODUCT_CODE, reportDate)
          .filter((report) => (
            (report.language_mode ?? "EN") === nextLanguageMode
            && report.revision === current.revision
            && report.lane === "PRODUCTION"
            && report.status !== "ARCHIVED"
          ))
          .sort((left, right) => right.version - left.version)[0]
        : selectReportForMonth(reportItems, PRODUCT_CODE, reportDate, nextLanguageMode);
      let detail: Report | null = null;
      if (!next && current) {
        const created = await api.createLanguageVariant(
          current.id,
          nextLanguageMode,
          current.latest_document?.version ?? 1,
        );
        reportItems = await api.listReports();
        next = reportItems.find((report) => report.id === created.id) ?? created;
      }
      if (next) {
        detail = await api.getReport(next.id);
        if (current && detail.status !== "FINALIZED") {
          await api.syncLanguageVariant(
            current.id,
            detail.id,
            current.latest_document?.version ?? 1,
            detail.latest_document?.version ?? 1,
          );
        }
        detail = await loadSelectedReport(next.id);
        reportItems = await api.listReports();
      }
      resetTransientState();
      setReports(reportItems);
      setSelected(detail);
      setLocale(nextLocale);
      if (detail) navigate(`/reports/${detail.id}`, { replace: true });
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
      resetTransientState();
      navigate(`/reports/${reportId}`);
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
      resetTransientState();
      navigate("/", { replace: true });
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
    if (!selected || isReportReadOnly(selected)) return;
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
    if (!selected || !selected.finalized_document_version) return;
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
      if (selected.status === "ARCHIVED") return;
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
  const dateLocale = locale === "zh-Hans" ? "zh-CN" : locale === "zh-Hant" ? "zh-HK" : "en";
  const productDisplayName = locale === "zh-Hans"
    ? (selected?.product_name || product?.name_zh_hans || product?.ticker || "3033")
    : locale === "zh-Hant"
      ? (selected?.product_name || product?.name_zh_hant || product?.ticker || "3033")
      : (product?.name_en ?? "CSOP Hang Seng TECH Index ETF");

  if (loading) return <div className="shell"><AppHeader busy /><main className="app-main"><div className="report-center-loading" role="status" aria-label={t("loadingReport")}><span /><span /><span /></div></main></div>;
  if (!selected) return <div className="shell"><AppHeader /><main className="app-main route-error"><FileText size={32} /><h2>{t("reportNotFound")}</h2><p>{error || t("reportNotFoundHelp")}</p><button className="primary" onClick={() => navigate("/")}><Home size={17} /> {t("backToReports")}</button></main></div>;

  const archived = selected.status === "ARCHIVED";
  const finalized = selected.status === "FINALIZED";
  const canDownload = Boolean(selected.finalized_document_version) && (!archived || artifactsByFormat.size > 0);
  const visibleOutputFormats = archived ? OUTPUT_FORMATS.filter(({ value }) => artifactsByFormat.has(value)) : OUTPUT_FORMATS;

  return <div className="shell">
    <AppHeader busy={busy} onLanguageChange={(next) => void changeLanguage(next)} />
    {error && <div className="error" role="alert">{error}</div>}
    <main className="app-main">
      <nav className="workspace-navigation" aria-label={t("workspaceNavigation")}>
        <button className="quiet-button" onClick={() => void navigateAfterSave("/")}><Home size={17} /> {t("reportCenter")}</button>
        <button className="quiet-button" onClick={() => void navigateAfterSave("/reports/new")}><Plus size={17} /> {t("newReport")}</button>
        {archived && <span className="read-only-badge"><Archive size={15} /> {t("archivedReadOnly")}</span>}
      </nav>
      <section className="report-context">
        <div className="fund-control">
          <label>{t("fund")}</label>
          <div className="fund-static" aria-label={`${t("fund")} 3033`}><strong>{productDisplayName}</strong><span>3033</span></div>
          <p>{product ? `${product.ticker} · ${locale !== "en" ? product.benchmark_code : (product.benchmark_name ?? product.benchmark_code)} · ${product.currency}` : `3033.HK · ${locale !== "en" ? "HSTECH" : "Hang Seng TECH Index"} · HKD`}</p>
        </div>
        <div className="report-controls">
          <label>{t("reportYear")}<input type="number" inputMode="numeric" min="1000" max="9999" step="1" value={reportYearInput} onChange={(event) => changeReportYear(event.target.value)} onBlur={() => { if (!/^\d{4}$/.test(reportYearInput)) setError(t("invalidYear")); }} disabled={busy} /></label>
          <label>{t("reportMonth")}<select value={reportDate.slice(5, 7)} onChange={(event) => void changeReportPeriod(reportYearInput, event.target.value)} disabled={busy || !/^\d{4}$/.test(reportYearInput)}>{MONTH_OPTIONS.map((month) => <option key={month} value={month}>{new Intl.DateTimeFormat(dateLocale, { month: "long", timeZone: "UTC" }).format(new Date(`2024-${month}-01T00:00:00Z`))}</option>)}</select></label>
          {productReports.length > 0 && <label>{t("reportVersion")}<select value={selected.id} onChange={(event) => void changeReport(event.target.value)} disabled={busy}>{productReports.map((report) => <option key={report.id} value={report.id}>{report.report_date} · r{report.revision} · {statusLabel(report.status)}</option>)}</select></label>}
          <>
            {!archived && <button className="danger-button" disabled={busy} onClick={() => void deleteReport()}><Trash2 size={17} /> {t("deleteReport")}</button>}
            <button title={t("preview")} disabled={busy} onClick={() => void openPreview()}><Eye size={17} /> {t("preview")}</button>
            {!archived && <button className="primary" disabled={busy || finalized} onClick={() => void reviewAndFinalize()}><FileCheck2 size={17} /> {finalized ? t("finalized") : t("finalize")}</button>}
            <div className="download-dropdown">
              <button
                disabled={busy || !canDownload}
                aria-haspopup="menu"
                aria-expanded={downloadsOpen}
                onClick={() => setDownloadsOpen((open) => !open)}
              ><Download size={17} /> {t("downloads")} <ChevronDown size={15} /></button>
              {downloadsOpen && canDownload && <div className="download-menu popover" role="menu" aria-label={t("downloadReport")}>
                {visibleOutputFormats.map(({ value, label }) => <button key={value} role="menuitem" onClick={() => void downloadOutput(value)}>
                  <Download size={16} />
                  <span><strong>{label}</strong><small>{artifactsByFormat.has(value) ? t("readyDownload") : t("generateDownload")}</small></span>
                </button>)}
              </div>}
            </div>
          </>
        </div>
      </section>
      <>
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
      </>
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

function App() {
  const router = useMemo(() => createBrowserRouter([
    { path: "/", element: <ReportsHome /> },
    { path: "/reports/new", element: <NewReportPage /> },
    { path: "/reports/:reportId", element: <ReportWorkspace /> },
    { path: "*", element: <ReportsHome /> },
  ]), []);
  return <RouterProvider router={router} />;
}

export default App;
