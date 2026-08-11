import { useDeferredValue, useEffect, useRef, useState } from "react";
import { DndContext, closestCenter, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, arrayMove, verticalListSortingStrategy, useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { AlertCircle, Check, ExternalLink, GripVertical, Plus, RefreshCw, Save, Search, X } from "lucide-react";
import {
  api,
  type CompanyNewsCatalogItem,
  type CompanyNewsCatalogPage,
  type NewsCandidateInput,
  type NewsSelectionDraft,
  type Report,
} from "../../api";

type RunAction = (work: () => Promise<unknown>) => Promise<void>;
type SnapshotNews = Record<string, unknown>;
type SortOrder = "newest" | "oldest";
type Importance = "" | "LOW" | "MEDIUM" | "HIGH";

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

export function toggleCatalogSelection(current: Draft[], item: CompanyNewsCatalogItem): Draft[] {
  const selectionKey = catalogSelectionKey(item);
  if (current.some((value) => value.selectionKey === selectionKey)) {
    return current.filter((value) => value.selectionKey !== selectionKey);
  }
  return [...current, {
    provider: "DA_REPORT",
    external_id: item.external_id,
    position: current.length,
    selectionKey,
    title: item.title,
    summary: item.summary,
    source: item.source_name,
    sourceUrl: item.source_url,
    publishedAt: item.published_at,
    ticker: null,
  }];
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

function publishedLabel(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("en-HK", {
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

function errorMessage(error: unknown): string {
  return String(error).replace(/^Error:\s*/, "") || "Unable to load DA-Report company news.";
}

function sentimentLabel(value: string | null): string {
  if (value === "bull") return "Bullish · 利好";
  if (value === "bear") return "Bearish · 利淡";
  if (value === "neutral") return "Neutral · 中性";
  return value || "Unrated";
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
  const sortable = useSortable({ id: item.selectionKey, disabled });
  return <article
    ref={sortable.setNodeRef}
    style={{ transform: CSS.Transform.toString(sortable.transform), transition: sortable.transition }}
    className="selected-news-card"
  >
    <header>
      <button className="icon-button news-drag-handle" title="Reorder news" {...sortable.attributes} {...sortable.listeners}><GripVertical size={17} /></button>
      <span>{item.ticker ?? (item.source || "DA-Report")}</span>
      <button className="icon-button danger" title="Remove" onClick={onRemove}><X size={15} /></button>
    </header>
    <input value={item.title} disabled={disabled} onChange={(event) => onUpdate({ ...item, title: event.target.value, title_override: event.target.value })} aria-label="Selected news title" />
    <textarea value={item.summary} disabled={disabled} onChange={(event) => onUpdate({ ...item, summary: event.target.value, summary_override: event.target.value })} aria-label="Selected news summary" />
    <footer>{item.source} · {publishedLabel(item.publishedAt)} HKT</footer>
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
      <label><span>Headline 標題</span><input value={form.title} onChange={set("title")} required /></label>
      <label><span>Publisher 來源</span><input value={form.source_name} onChange={set("source_name")} required /></label>
      <label><span>Article URL 連結</span><input type="url" value={form.source_url} onChange={set("source_url")} required /></label>
      <label><span>Published 發布時間</span><input type="datetime-local" value={form.published_at} onChange={set("published_at")} required /></label>
      <label><span>Ticker 代號</span><input value={form.ticker ?? ""} onChange={set("ticker")} /></label>
      <label className="news-add-wide"><span>Summary 摘要</span><textarea value={form.summary} onChange={set("summary")} /></label>
    </div>
    <div className="news-add-actions">
      <button type="button" onClick={onCancel}>Cancel 取消</button>
      <button type="submit" className="primary" disabled={busy || !ready}><Plus size={15} /> Add 新增</button>
    </div>
  </form>;
}

export function CompanyNewsWorkbench({
  report,
  busy,
  run,
  selectedSnapshot,
}: {
  report: Report;
  busy: boolean;
  run: RunAction;
  selectedSnapshot: SnapshotNews[];
}) {
  const version = report.latest_document?.version ?? 1;
  const readOnly = report.status === "FINALIZED";
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
  const [source, setSource] = useState("");
  const [sentiment, setSentiment] = useState("");
  const [importance, setImportance] = useState<Importance>("");
  const [sort, setSort] = useState<SortOrder>("newest");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [adding, setAdding] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const generation = useRef(0);
  const listRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const loadMoreRef = useRef<() => void>(() => undefined);

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
    void api.listCompanyNewsCatalog(report.id, {
      query: deferredQuery.trim() || undefined,
      source: source || undefined,
      sentiment: sentiment || undefined,
      importance: importance || undefined,
      from_date: fromDate || undefined,
      to_date: toDate || undefined,
      sort,
      limit: 50,
    }).then((page) => {
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
  }, [report.id, deferredQuery, source, sentiment, importance, fromDate, toDate, sort, refreshToken]);

  loadMoreRef.current = () => {
    if (loading || loadingMore || !hasMore || !nextCursor) return;
    const requestGeneration = generation.current;
    setLoadingMore(true);
    setCatalogError("");
    void api.listCompanyNewsCatalog(report.id, {
      query: deferredQuery.trim() || undefined,
      source: source || undefined,
      sentiment: sentiment || undefined,
      importance: importance || undefined,
      from_date: fromDate || undefined,
      to_date: toDate || undefined,
      sort,
      cursor: nextCursor,
      limit: 50,
    }).then((page) => {
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
  const toggle = (item: CompanyNewsCatalogItem) => setSelected((current) => toggleCatalogSelection(current, item));
  const dragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    setSelected((items) => arrayMove(
      items,
      items.findIndex((item) => item.selectionKey === active.id),
      items.findIndex((item) => item.selectionKey === over.id),
    ));
  };
  const save = () => {
    const selections: NewsSelectionDraft[] = selected.map((item, position) => ({
      ...(item.news_item_id
        ? { news_item_id: item.news_item_id }
        : { provider: "DA_REPORT" as const, external_id: item.external_id }),
      position,
      title_override: item.title_override,
      summary_override: item.summary_override,
    }));
    return run(() => api.selectNews(report.id, version, selections));
  };
  const addManual = (item: NewsCandidateInput) => run(async () => {
    const created = await api.addNewsCandidate(report.id, item);
    setSelected((current) => [...current, manualDraft(created, current.length)]);
    setAdding(false);
  });
  const resetFilters = () => {
    setQuery("");
    setSource("");
    setSentiment("");
    setImportance("");
    setFromDate("");
    setToDate("");
    setSort("newest");
  };
  const filtered = Boolean(query || source || sentiment || importance || fromDate || toDate || sort !== "newest");
  const displayedFromDate = fromDate || facets.date_min || "";
  const displayedToDate = toDate || facets.date_max || "";

  return <div className="news-workbench news-catalog-workbench">
    <section className="news-column news-candidates">
      <header className="news-panel-head">
        <div className="news-panel-title"><h3>News &amp; Report</h3><span>新聞與報告</span></div>
        <div className="news-panel-count"><strong>{catalog.length}</strong><small>of {total}</small></div>
        <button disabled={loading} onClick={() => setRefreshToken((value) => value + 1)} title="Reload DA-Report company news"><RefreshCw size={15} className={loading ? "spin" : ""} /> Refresh</button>
      </header>

      <div className="news-panel-filters">
        <label className="search-field news-catalog-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索標題或正文 Search headline or summary" aria-label="Search company news" /></label>
        <select value={source} onChange={(event) => setSource(event.target.value)} aria-label="Filter by source">
          <option value="">全部來源 All sources</option>
          {facets.sources.map((item) => <option key={item.value} value={item.value}>{item.label} ({item.count})</option>)}
        </select>
        <select value={sentiment} onChange={(event) => setSentiment(event.target.value)} aria-label="Filter by sentiment">
          <option value="">全部情緒 All sentiment</option>
          {Object.entries(facets.sentiments).map(([value, count]) => <option key={value} value={value}>{sentimentLabel(value)} ({count})</option>)}
        </select>
        <select value={importance} onChange={(event) => setImportance(event.target.value as Importance)} aria-label="Filter by importance">
          <option value="">全部重要度 All importance</option>
          {(["HIGH", "MEDIUM", "LOW"] as const).map((value) => <option key={value} value={value}>{value} ({facets.importance[value] ?? 0})</option>)}
        </select>
        <div className="news-date-range">
          <input type="date" value={displayedFromDate} max={displayedToDate || undefined} onChange={(event) => setFromDate(event.target.value)} aria-label="From date" />
          <span aria-hidden="true">→</span>
          <input type="date" value={displayedToDate} min={displayedFromDate || undefined} onChange={(event) => setToDate(event.target.value)} aria-label="To date" />
        </div>
        <div className="scope-control news-sort-control" role="group" aria-label="Sort order">
          <button className={sort === "newest" ? "active" : ""} onClick={() => setSort("newest")}>最新在前</button>
          <button className={sort === "oldest" ? "active" : ""} onClick={() => setSort("oldest")}>最舊在前</button>
        </div>
        <button className="news-add-button" disabled={busy || readOnly} onClick={() => setAdding((open) => !open)}><Plus size={15} /> 添加新闻</button>
        {filtered && <button className="news-reset" onClick={resetFilters}><X size={14} /> 清除筛选</button>}
      </div>

      {adding && <AddNewsForm reportDate={report.report_date} busy={busy} onCancel={() => setAdding(false)} onSubmit={addManual} />}

      <div className="news-list news-catalog-list" ref={listRef}>
        {loading && !catalog.length && <div className="skeleton-list" role="status" aria-label="Loading company news">{[0, 1, 2, 3].map((index) => <div className="skeleton skeleton-card" key={index} />)}</div>}
        {!loading && catalog.map((item) => {
          const selectionKey = catalogSelectionKey(item);
          const isSelected = selectedKeys.has(selectionKey);
          const translatedTitle = item.title_zh && item.title_zh !== item.title ? item.title_zh : null;
          const summary = item.summary_zh || item.summary_en || item.summary;
          return <article className={`news-item ${isSelected ? "selected" : ""}`} data-external-id={item.external_id} key={selectionKey}>
            <input type="checkbox" className="news-checkbox" checked={isSelected} disabled={readOnly} onChange={() => toggle(item)} aria-label={`Select ${item.title}`} />
            <div className="news-item-body">
              <h3>{item.title_en || item.title}</h3>
              {translatedTitle && <h4 className="news-item-translation">{translatedTitle}</h4>}
              {summary && <p>{summary}</p>}
              <footer>
                <span className="news-chip category">Corporate · 公司新聞</span>
                <span className={`news-chip sentiment sentiment-${item.sentiment ?? "unknown"}`}>{sentimentLabel(item.sentiment)}</span>
                {item.importance_score !== null && <span className="news-chip importance">Importance {Math.round(item.importance_score)}</span>}
                {item.region && <span className="news-chip region">{item.region}</span>}
                <span className="news-meta">{item.source_name}</span>
                <time dateTime={item.published_at}>{publishedLabel(item.published_at)}</time>
                <span className="news-chip tz">HKT</span>
                {item.published_at_source === "fetched_at" && <span className="news-meta">Fetched time</span>}
                <a href={item.source_url} target="_blank" rel="noreferrer">Source <ExternalLink size={12} /></a>
              </footer>
            </div>
          </article>;
        })}
        {catalogError && <div className="news-catalog-error" role="alert"><AlertCircle size={18} /><span>{catalogError}</span><button onClick={() => catalog.length ? loadMoreRef.current() : setRefreshToken((value) => value + 1)}>Retry</button></div>}
        {!loading && !catalog.length && !catalogError && <div className="news-empty"><RefreshCw size={20} /><strong>No company news found</strong><span>Adjust the filters or refresh the DA-Report snapshot.</span></div>}
        {loadingMore && <div className="news-load-more" role="status"><RefreshCw className="spin" size={16} /><span>Loading more</span></div>}
        <div ref={sentinelRef} className="news-scroll-sentinel" aria-hidden="true" />
      </div>
    </section>

    <section className="news-column news-selected-column">
      <header className="news-panel-head">
        <div className="news-panel-title"><h3>Selected for report</h3><span>已選新聞</span></div>
        <div className="news-panel-count"><strong>{selected.length}</strong></div>
        <button className="primary" disabled={busy || readOnly} onClick={save}><Save size={15} /> Save</button>
      </header>
      <DndContext collisionDetection={closestCenter} onDragEnd={dragEnd}>
        <SortableContext items={selected.map((item) => item.selectionKey)} strategy={verticalListSortingStrategy}>
          <div className="news-list">
            {selected.map((item) => <SortableSelected key={item.selectionKey} item={item} disabled={readOnly} onUpdate={(next) => setSelected((items) => items.map((value) => value.selectionKey === next.selectionKey ? next : value))} onRemove={() => setSelected((items) => items.filter((value) => value.selectionKey !== item.selectionKey))} />)}
            {!selected.length && <div className="news-empty"><Check size={20} /><strong>No news selected</strong><span>Select catalog items to build the Company News page.</span></div>}
          </div>
        </SortableContext>
      </DndContext>
    </section>
  </div>;
}
