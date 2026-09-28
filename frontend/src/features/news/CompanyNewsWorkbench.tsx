import { useCallback, useDeferredValue, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { DndContext, closestCenter, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, arrayMove, verticalListSortingStrategy, useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { AlertCircle, Check, ExternalLink, GripVertical, Plus, RefreshCw, Save, Search, X } from "lucide-react";
import {
  api,
  type CompanyNewsCatalogItem,
  type CompanyNewsCatalogPage,
  type CompanyNewsCatalogQuery,
  type NewsCandidateInput,
  type NewsSelectionDraft,
  type Report,
} from "../../api";
import type { RegisterPendingSave } from "../../pendingSave";
import { useLocale, type Locale } from "../../i18n";
import { isReportReadOnly } from "../../reportModules";

type RunAction = (work: () => Promise<unknown>) => Promise<void>;
type SnapshotNews = Record<string, unknown>;
type SortOrder = "newest" | "oldest";
type SentimentFilter = "" | "bull" | "neutral" | "bear";
type CompanyScope = "" | "CONSTITUENTS";
const IGNORE_PENDING_SAVE: RegisterPendingSave = () => undefined;
const SENTIMENT_FILTERS: Array<{ value: SentimentFilter; label: "allSentiment" | "bullish" | "neutral" | "bearish" }> = [
  { value: "", label: "allSentiment" },
  { value: "bull", label: "bullish" },
  { value: "neutral", label: "neutral" },
  { value: "bear", label: "bearish" },
];

export interface Draft extends NewsSelectionDraft {
  selectionKey: string;
  title: string;
  summary: string;
  source: string;
  sourceUrl: string;
  publishedAt: string;
  ticker: string | null;
}

const HKT = "Asia/Hong_Kong";
const EMPTY_FACETS: CompanyNewsCatalogPage["facets"] = {
  companies: [],
  sources: [],
  sentiments: {},
  importance: {},
  date_min: null,
  date_max: null,
};

export function catalogSelectionKey(item: Pick<CompanyNewsCatalogItem, "provider" | "external_id">): string {
  return `${item.provider}:${item.external_id}`;
}

export function mergeCatalogItems(
  current: CompanyNewsCatalogItem[],
  incoming: CompanyNewsCatalogItem[],
): CompanyNewsCatalogItem[] {
  const byKey = new Map(current.map((item) => [catalogSelectionKey(item), item]));
  for (const item of incoming) byKey.set(catalogSelectionKey(item), item);
  return [...byKey.values()];
}

export function draftsFromSnapshot(selectedSnapshot: SnapshotNews[], reportDate: string): Draft[] {
  return selectedSnapshot.flatMap((item, index) => {
    const newsItemId = String(item.news_item_id ?? "");
    if (!newsItemId) return [];
    const provider = item.provider === "DA_REPORT" && item.external_id ? "DA_REPORT" as const : undefined;
    const externalId = provider ? String(item.external_id) : undefined;
    return [{
      news_item_id: newsItemId,
      provider,
      external_id: externalId,
      position: index,
      selectionKey: provider && externalId ? `${provider}:${externalId}` : `LOCAL:${newsItemId}`,
      title: String(item.title ?? ""),
      summary: String(item.summary ?? ""),
      source: String(item.source_name ?? ""),
      sourceUrl: String(item.source_url ?? ""),
      publishedAt: String(item.published_at ?? reportDate),
      ticker: String(item.ticker ?? "") || null,
      title_override: String(item.title ?? ""),
      summary_override: String(item.summary ?? ""),
    }];
  });
}

export function toggleCatalogSelection(current: Draft[], item: CompanyNewsCatalogItem, locale: Locale = "en"): Draft[] {
  const selectionKey = catalogSelectionKey(item);
  if (current.some((value) => value.selectionKey === selectionKey)) {
    return current.filter((value) => value.selectionKey !== selectionKey);
  }
  return [...current, {
    provider: "DA_REPORT",
    external_id: item.external_id,
    position: current.length,
    selectionKey,
    title: locale === "zh-Hans" ? (item.title_zh_hans ?? "") : locale === "zh-Hant" ? (item.title_zh ?? "") : (item.title_en ?? item.title),
    summary: locale === "zh-Hans" ? (item.summary_zh_hans ?? "") : locale === "zh-Hant" ? (item.summary_zh ?? "") : (item.summary_en ?? item.summary),
    source: locale === "zh-Hans" ? (item.source_name_zh_hans ?? "") : locale === "zh-Hant" ? (item.source_name_zh ?? "") : item.source_name,
    sourceUrl: item.source_url,
    publishedAt: item.published_at,
    ticker: null,
  }];
}

function selectionPayload(items: Draft[]): NewsSelectionDraft[] {
  return items.map((item, position) => ({
    ...(item.news_item_id
      ? { news_item_id: item.news_item_id }
      : { provider: "DA_REPORT" as const, external_id: item.external_id }),
    position,
    title_override: item.title_override,
    summary_override: item.summary_override,
  }));
}

function manualDraft(item: Awaited<ReturnType<typeof api.addNewsCandidate>>, position: number): Draft {
  return {
    news_item_id: item.id,
    position,
    selectionKey: `LOCAL:${item.id}`,
    title: item.title,
    summary: item.summary,
    source: item.source_name,
    sourceUrl: item.source_url,
    publishedAt: item.published_at,
    ticker: item.ticker,
  };
}

function publishedLabel(value: string, locale: Locale = "en"): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(locale === "zh-Hans" ? "zh-CN" : locale === "zh-Hant" ? "zh-HK" : "en-HK", {
    timeZone: HKT,
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function publishedDateHkt(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value.slice(0, 10);
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: HKT,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(parsed);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export function reportYearDateRange(reportDate: string): { fromDate: string; toDate: string } {
  const year = reportDate.slice(0, 4);
  return { fromDate: `${year}-01-01`, toDate: `${year}-12-31` };
}

export function buildCompanyNewsCatalogQuery({
  query,
  companyScope,
  source,
  sentiment,
  fromDate,
  toDate,
  sort,
  cursor,
}: {
  query: string;
  companyScope: CompanyScope;
  source: string;
  sentiment: SentimentFilter;
  fromDate: string;
  toDate: string;
  sort: SortOrder;
  cursor?: string;
}): CompanyNewsCatalogQuery {
  return {
    query: query.trim() || undefined,
    company_scope: companyScope || undefined,
    source: source || undefined,
    sentiment: sentiment || undefined,
    from_date: fromDate,
    to_date: toDate,
    sort,
    cursor,
    limit: 50,
  };
}

function errorMessage(error: unknown): string {
  return String(error).replace(/^Error:\s*/, "") || "Unable to load DA-Report company news.";
}

function sentimentLabel(value: string | null, locale: Locale, t: ReturnType<typeof useLocale>["t"]): string {
  if (value === "bull") return t("bullish");
  if (value === "bear") return t("bearish");
  if (value === "neutral") return t("neutral");
  return value || t("unrated");
}

function SortableSelected({
  item,
  disabled,
  onUpdate,
  onRemove,
}: {
  item: Draft;
  disabled: boolean;
  onUpdate: (item: Draft) => void;
  onRemove: () => void;
}) {
  const { locale, t } = useLocale();
  const sortable = useSortable({ id: item.selectionKey, disabled });
  return <article
    ref={sortable.setNodeRef}
    style={{ transform: CSS.Transform.toString(sortable.transform), transition: sortable.transition }}
    className="selected-news-card"
  >
    <header>
      <button className="icon-button news-drag-handle" title={t("reorderNews")} {...sortable.attributes} {...sortable.listeners}><GripVertical size={17} /></button>
      <span>{item.ticker ?? (item.source || "DA-Report")}</span>
      <button className="icon-button danger" title={t("remove")} onClick={onRemove}><X size={15} /></button>
    </header>
    <input value={item.title} disabled={disabled} onChange={(event) => onUpdate({ ...item, title: event.target.value, title_override: event.target.value })} aria-label={t("selectedNewsTitle")} />
    <textarea value={item.summary} disabled={disabled} onChange={(event) => onUpdate({ ...item, summary: event.target.value, summary_override: event.target.value })} aria-label={t("selectedNewsSummary")} />
    <footer>{item.source} · {publishedLabel(item.publishedAt, locale)} HKT</footer>
  </article>;
}

const EMPTY_MANUAL: NewsCandidateInput = {
  title: "",
  summary: "",
  source_name: "",
  source_url: "",
  published_at: "",
  ticker: null,
};

function AddNewsForm({
  reportDate,
  busy,
  onCancel,
  onSubmit,
}: {
  reportDate: string;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (item: NewsCandidateInput) => void;
}) {
  const { t } = useLocale();
  const [form, setForm] = useState<NewsCandidateInput>({ ...EMPTY_MANUAL, published_at: `${reportDate}T09:00` });
  const set = (key: keyof NewsCandidateInput) => (event: { target: { value: string } }) => {
    setForm((current) => ({ ...current, [key]: event.target.value }));
  };
  const ready = form.title.trim() && form.source_name.trim() && /^https?:\/\/\S+$/.test(form.source_url.trim()) && form.published_at;
  return <form className="news-add-form" onSubmit={(event) => {
    event.preventDefault();
    onSubmit({
      ...form,
      published_at: new Date(form.published_at).toISOString(),
      ticker: form.ticker?.trim() ? form.ticker.trim().toUpperCase() : null,
    });
  }}>
    <div className="news-add-grid">
      <label><span>{t("headline")}</span><input value={form.title} onChange={set("title")} required /></label>
      <label><span>{t("publisher")}</span><input value={form.source_name} onChange={set("source_name")} required /></label>
      <label><span>{t("articleUrl")}</span><input type="url" value={form.source_url} onChange={set("source_url")} required /></label>
      <label><span>{t("publishedAt")}</span><input type="datetime-local" value={form.published_at} onChange={set("published_at")} required /></label>
      <label><span>{t("ticker")}</span><input value={form.ticker ?? ""} onChange={set("ticker")} /></label>
      <label className="news-add-wide"><span>{t("summary")}</span><textarea value={form.summary} onChange={set("summary")} /></label>
    </div>
    <div className="news-add-actions">
      <button type="button" onClick={onCancel}>{t("cancel")}</button>
      <button type="submit" className="primary" disabled={busy || !ready}><Plus size={15} /> {t("add")}</button>
    </div>
  </form>;
}

export function CompanyNewsWorkbench({
  report,
  busy,
  run,
  selectedSnapshot,
  registerPendingSave = IGNORE_PENDING_SAVE,
}: {
  report: Report;
  busy: boolean;
  run: RunAction;
  selectedSnapshot: SnapshotNews[];
  registerPendingSave?: RegisterPendingSave;
}) {
  const { locale, t } = useLocale();
  const version = report.latest_document?.version ?? 1;
  const readOnly = isReportReadOnly(report);
  const [catalog, setCatalog] = useState<CompanyNewsCatalogItem[]>([]);
  const [facets, setFacets] = useState<CompanyNewsCatalogPage["facets"]>(EMPTY_FACETS);
  const [total, setTotal] = useState(0);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [selected, setSelected] = useState<Draft[]>(() => draftsFromSnapshot(selectedSnapshot, report.report_date));
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const [companyScope, setCompanyScope] = useState<CompanyScope>("");
  const [source, setSource] = useState("");
  const [sentiment, setSentiment] = useState<SentimentFilter>("");
  const [sort, setSort] = useState<SortOrder>("newest");
  const reportYearRange = useMemo(() => reportYearDateRange(report.report_date), [report.report_date]);
  const [fromDate, setFromDate] = useState(reportYearRange.fromDate);
  const [toDate, setToDate] = useState(reportYearRange.toDate);
  const [adding, setAdding] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const generation = useRef(0);
  const listRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const loadMoreRef = useRef<() => void>(() => undefined);
  const initialSelection = useMemo(
    () => JSON.stringify(selectionPayload(draftsFromSnapshot(selectedSnapshot, report.report_date))),
    [report.id, version],
  );

  useEffect(() => {
    setSelected(draftsFromSnapshot(selectedSnapshot, report.report_date));
  }, [report.id, version]);

  useEffect(() => {
    const requestGeneration = ++generation.current;
    setLoading(true);
    setCatalogError("");
    setCatalog([]);
    setNextCursor(null);
    setHasMore(false);
    void api.listCompanyNewsCatalog(report.id, buildCompanyNewsCatalogQuery({
      query: deferredQuery,
      companyScope,
      source,
      sentiment,
      fromDate,
      toDate,
      sort,
    })).then((page) => {
      if (generation.current !== requestGeneration) return;
      setCatalog(page.items);
      setFacets(page.facets);
      setTotal(page.total);
      setNextCursor(page.next_cursor);
      setHasMore(page.has_more);
    }).catch((error) => {
      if (generation.current === requestGeneration) setCatalogError(errorMessage(error));
    }).finally(() => {
      if (generation.current === requestGeneration) setLoading(false);
    });
  }, [report.id, deferredQuery, companyScope, source, sentiment, fromDate, toDate, sort, refreshToken]);

  loadMoreRef.current = () => {
    if (loading || loadingMore || !hasMore || !nextCursor) return;
    const requestGeneration = generation.current;
    setLoadingMore(true);
    setCatalogError("");
    void api.listCompanyNewsCatalog(report.id, buildCompanyNewsCatalogQuery({
      query: deferredQuery,
      companyScope,
      source,
      sentiment,
      fromDate,
      toDate,
      sort,
      cursor: nextCursor,
    })).then((page) => {
      if (generation.current !== requestGeneration) return;
      setCatalog((current) => mergeCatalogItems(current, page.items));
      setFacets(page.facets);
      setTotal(page.total);
      setNextCursor(page.next_cursor);
      setHasMore(page.has_more);
    }).catch((error) => {
      if (generation.current === requestGeneration) setCatalogError(errorMessage(error));
    }).finally(() => {
      if (generation.current === requestGeneration) setLoadingMore(false);
    });
  };

  useEffect(() => {
    const target = sentinelRef.current;
    const root = listRef.current;
    if (!target || !root || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) loadMoreRef.current();
    }, { root, rootMargin: "160px" });
    observer.observe(target);
    return () => observer.disconnect();
  }, []);

  const selectedKeys = new Set(selected.map((item) => item.selectionKey));
  const toggle = (item: CompanyNewsCatalogItem) => setSelected((current) => toggleCatalogSelection(current, item, locale));
  const dragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    setSelected((items) => arrayMove(
      items,
      items.findIndex((item) => item.selectionKey === active.id),
      items.findIndex((item) => item.selectionKey === over.id),
    ));
  };
  const persist = useCallback(
    async () => { await api.selectNews(report.id, version, selectionPayload(selected)); },
    [report.id, selected, version],
  );
  const dirty = !readOnly && JSON.stringify(selectionPayload(selected)) !== initialSelection;
  useLayoutEffect(() => {
    registerPendingSave(dirty ? persist : null);
    return () => registerPendingSave(null);
  }, [dirty, persist, registerPendingSave]);
  const save = () => run(persist);
  const addManual = (item: NewsCandidateInput) => run(async () => {
    const created = await api.addNewsCandidate(report.id, item);
    setSelected((current) => [...current, manualDraft(created, current.length)]);
    setAdding(false);
  });
  const resetFilters = () => {
    setQuery("");
    setCompanyScope("");
    setSource("");
    setSentiment("");
    setFromDate(reportYearRange.fromDate);
    setToDate(reportYearRange.toDate);
    setSort("newest");
  };
  const filtered = Boolean(
    query
    || companyScope
    || source
    || sentiment
    || fromDate !== reportYearRange.fromDate
    || toDate !== reportYearRange.toDate
    || sort !== "newest"
  );

  return <div className="news-workbench news-catalog-workbench">
    <section className="news-column news-candidates">
      <header className="news-panel-head">
        <div className="news-panel-title"><h3>{t("newsAndReport")}</h3></div>
        <div className="news-panel-count"><strong>{catalog.length}</strong><small>{t("ofTotal", { total })}</small></div>
        <button disabled={loading} onClick={() => setRefreshToken((value) => value + 1)} title={t("reloadNews")}><RefreshCw size={15} className={loading ? "spin" : ""} /> {t("refresh")}</button>
      </header>

      <div className="news-panel-filters">
        <label className="search-field news-catalog-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("searchNews")} aria-label={t("searchCompanyNews")} /></label>
        <div className="scope-control news-company-scope" role="group" aria-label={t("filterCompany")}>
          <button className={companyScope === "" ? "active" : ""} aria-pressed={companyScope === ""} onClick={() => setCompanyScope("")}>{t("allCompanies")}</button>
          <button
            className={companyScope === "CONSTITUENTS" ? "active" : ""}
            aria-pressed={companyScope === "CONSTITUENTS"}
            disabled={!facets.companies.length}
            title={facets.companies.length ? t("constituentCompanies") : t("constituentUnavailable")}
            onClick={() => setCompanyScope("CONSTITUENTS")}
          >{t("constituentCompanies")}</button>
        </div>
        <select value={source} onChange={(event) => setSource(event.target.value)} aria-label={t("filterSource")}>
          <option value="">{t("allSources")}</option>
          {facets.sources.map((item) => <option key={item.value} value={item.value}>{locale === "zh-Hans" ? (item.label_zh_hans ?? item.value) : locale === "zh-Hant" ? (item.label_zh ?? item.value) : item.label}</option>)}
        </select>
        <div className="scope-control news-company-scope" role="group" aria-label={t("filterSentiment")}>
          {SENTIMENT_FILTERS.map((option) => <button
            key={option.value || "all"}
            className={sentiment === option.value ? "active" : ""}
            aria-pressed={sentiment === option.value}
            onClick={() => setSentiment(option.value)}
          >{t(option.label)}</button>)}
        </div>
        <div className="news-date-range">
          <input type="date" value={fromDate} max={toDate || undefined} onChange={(event) => setFromDate(event.target.value)} aria-label={t("fromDate")} />
          <span aria-hidden="true">→</span>
          <input type="date" value={toDate} min={fromDate || undefined} onChange={(event) => setToDate(event.target.value)} aria-label={t("toDate")} />
        </div>
        <div className="scope-control news-sort-control" role="group" aria-label={t("sortOrder")}>
          <button className={sort === "newest" ? "active" : ""} onClick={() => setSort("newest")}>{t("newest")}</button>
          <button className={sort === "oldest" ? "active" : ""} onClick={() => setSort("oldest")}>{t("oldest")}</button>
        </div>
        <button className="news-add-button" disabled={busy || readOnly} onClick={() => setAdding((open) => !open)}><Plus size={15} /> {t("addNews")}</button>
        {filtered && <button className="news-reset" onClick={resetFilters}><X size={14} /> {t("clearFilters")}</button>}
      </div>

      {adding && <AddNewsForm reportDate={report.report_date} busy={busy} onCancel={() => setAdding(false)} onSubmit={addManual} />}

      <div className="news-list news-catalog-list" ref={listRef}>
        {loading && !catalog.length && <div className="skeleton-list" role="status" aria-label={t("loadingNews")}>{[0, 1, 2, 3].map((index) => <div className="skeleton skeleton-card" key={index} />)}</div>}
        {!loading && catalog.map((item) => {
          const selectionKey = catalogSelectionKey(item);
          const isSelected = selectedKeys.has(selectionKey);
          const displayTitle = locale === "zh-Hans" ? (item.title_zh_hans ?? "") : locale === "zh-Hant" ? (item.title_zh ?? "") : (item.title_en ?? item.title);
          const summary = locale === "zh-Hans" ? (item.summary_zh_hans ?? "") : locale === "zh-Hant" ? (item.summary_zh ?? "") : (item.summary_en ?? item.summary);
          return <article className={`news-item ${isSelected ? "selected" : ""}`} data-external-id={item.external_id} key={selectionKey}>
            <input type="checkbox" className="news-checkbox" checked={isSelected} disabled={readOnly} onChange={() => toggle(item)} aria-label={t("selectNews", { title: displayTitle })} />
            <div className="news-item-body">
              <h3>{displayTitle}</h3>
              {summary && <p>{summary}</p>}
              <footer>
                <span className="news-chip category">{t("corporate")}</span>
                <span className={`news-chip sentiment sentiment-${item.sentiment ?? "unknown"}`}>{sentimentLabel(item.sentiment, locale, t)}</span>
                {item.importance_score !== null && <span className="news-chip importance">{t("importance", { score: Math.round(item.importance_score) })}</span>}
                {item.region && <span className="news-chip region">{locale === "zh-Hans" && item.region === "China" ? "中国" : locale === "zh-Hant" && item.region === "China" ? "中國" : item.region}</span>}
                <span className="news-meta">{locale === "zh-Hans" ? (item.source_name_zh_hans ?? "") : locale === "zh-Hant" ? (item.source_name_zh ?? "") : item.source_name}</span>
                <time dateTime={item.published_at}>{publishedLabel(item.published_at, locale)}</time>
                <span className="news-chip tz">HKT</span>
                {item.published_at_source === "fetched_at" && <span className="news-meta">{t("fetchedTime")}</span>}
                <a href={item.source_url} target="_blank" rel="noreferrer">{t("source")} <ExternalLink size={12} /></a>
              </footer>
            </div>
          </article>;
        })}
        {catalogError && <div className="news-catalog-error" role="alert"><AlertCircle size={18} /><span>{catalogError}</span><button onClick={() => catalog.length ? loadMoreRef.current() : setRefreshToken((value) => value + 1)}>{t("retry")}</button></div>}
        {!loading && !catalog.length && !catalogError && <div className="news-empty"><RefreshCw size={20} /><strong>{t("noNewsFound")}</strong><span>{t("adjustFilters")}</span></div>}
        {loadingMore && <div className="news-load-more" role="status"><RefreshCw className="spin" size={16} /><span>{t("loadingMore")}</span></div>}
        <div ref={sentinelRef} className="news-scroll-sentinel" aria-hidden="true" />
      </div>
    </section>

    <section className="news-column news-selected-column">
      <header className="news-panel-head">
        <div className="news-panel-title"><h3>{t("selectedForReport")}</h3></div>
        <div className="news-panel-count"><strong>{selected.length}</strong></div>
        <button className="primary" disabled={busy || readOnly || !dirty} onClick={save}><Save size={15} /> {t("save")}</button>
      </header>
      <DndContext collisionDetection={closestCenter} onDragEnd={dragEnd}>
        <SortableContext items={selected.map((item) => item.selectionKey)} strategy={verticalListSortingStrategy}>
          <div className="news-list news-selected-list">
            {selected.map((item) => <SortableSelected key={item.selectionKey} item={item} disabled={readOnly} onUpdate={(next) => setSelected((items) => items.map((value) => value.selectionKey === next.selectionKey ? next : value))} onRemove={() => setSelected((items) => items.filter((value) => value.selectionKey !== item.selectionKey))} />)}
            {!selected.length && <div className="news-empty"><Check size={20} /><strong>{t("noNewsSelected")}</strong><span>{t("selectNewsHelp")}</span></div>}
          </div>
        </SortableContext>
      </DndContext>
    </section>
  </div>;
}
