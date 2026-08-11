import { useEffect, useMemo, useRef, useState } from "react";
import { DndContext, closestCenter, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, arrayMove, verticalListSortingStrategy, useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Check, ExternalLink, GripVertical, Plus, RefreshCw, Save, Search, X } from "lucide-react";
import { api, type NewsCandidate, type NewsCandidateInput, type NewsProvider, type NewsSelectionDraft, type Report } from "../../api";

type RunAction = (work: () => Promise<unknown>) => Promise<void>;
type SnapshotNews = Record<string, unknown>;
type SortOrder = "newest" | "oldest";

export interface Draft extends NewsSelectionDraft { title: string; summary: string; source: string; publishedAt: string; ticker: string | null; }

const HKT = "Asia/Hong_Kong";

export function matchesNewsSource(item: NewsCandidate, sourceFilter: string): boolean {
  return !sourceFilter || item.source_name === sourceFilter;
}

interface AutoLoadState {
  busy: boolean;
  candidateCount: number;
  daConfigured: boolean;
  loading: boolean;
  readOnly: boolean;
  attempted: boolean;
}

export function shouldAutoLoadDaNews(state: AutoLoadState): boolean {
  return !state.busy
    && !state.loading
    && !state.readOnly
    && state.daConfigured
    && !state.attempted;
}

export function reportNewsWindow(reportDate: string): { fromDate: string; toDate: string } {
  return { fromDate: `${reportDate.slice(0, 8)}01`, toDate: reportDate };
}

export function draftsFromSnapshot(selectedSnapshot: SnapshotNews[], reportDate: string): Draft[] {
  return selectedSnapshot.filter((item) => item.news_item_id).map((item, index) => ({
    news_item_id: String(item.news_item_id),
    position: index,
    title: String(item.title ?? ""),
    summary: String(item.summary ?? ""),
    source: String(item.source_name ?? ""),
    publishedAt: String(item.published_at ?? reportDate),
    ticker: String(item.ticker ?? "") || null,
    title_override: String(item.title ?? ""),
    summary_override: String(item.summary ?? ""),
  }));
}

export function toggleNewsSelection(current: Draft[], item: NewsCandidate): Draft[] {
  if (current.some((value) => value.news_item_id === item.id)) {
    return current.filter((value) => value.news_item_id !== item.id);
  }
  return [...current, {
    news_item_id: item.id,
    position: current.length,
    title: item.title,
    summary: item.summary,
    source: item.source_name,
    publishedAt: item.published_at,
    ticker: item.ticker,
  }];
}

function publishedLabel(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("en-HK", { timeZone: HKT, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
}

export function publishedDateHkt(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value.slice(0, 10);
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: HKT, year: "numeric", month: "2-digit", day: "2-digit" })
    .formatToParts(parsed);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function SortableSelected({ item, disabled, onUpdate, onRemove }: { item: Draft; disabled: boolean; onUpdate: (item: Draft) => void; onRemove: () => void }) {
  const sortable = useSortable({ id: item.news_item_id, disabled });
  return <article ref={sortable.setNodeRef} style={{ transform: CSS.Transform.toString(sortable.transform), transition: sortable.transition }} className="selected-news-card">
    <header><button className="icon-button news-drag-handle" title="Reorder news" {...sortable.attributes} {...sortable.listeners}><GripVertical size={17} /></button><span>{item.ticker ?? "General"}</span><button className="icon-button danger" title="Remove" onClick={onRemove}><X size={15} /></button></header>
    <input value={item.title} disabled={disabled} onChange={(event) => onUpdate({ ...item, title: event.target.value, title_override: event.target.value })} aria-label="Selected news title" />
    <textarea value={item.summary} disabled={disabled} onChange={(event) => onUpdate({ ...item, summary: event.target.value, summary_override: event.target.value })} aria-label="Selected news summary" />
    <footer>{item.source} · {publishedLabel(item.publishedAt)} HKT</footer>
  </article>;
}

const EMPTY_MANUAL: NewsCandidateInput = { title: "", summary: "", source_name: "", source_url: "", published_at: "", ticker: null };

function AddNewsForm({ reportDate, busy, onCancel, onSubmit }: { reportDate: string; busy: boolean; onCancel: () => void; onSubmit: (item: NewsCandidateInput) => void }) {
  const [form, setForm] = useState<NewsCandidateInput>({ ...EMPTY_MANUAL, published_at: `${reportDate}T09:00` });
  const set = (key: keyof NewsCandidateInput) => (event: { target: { value: string } }) => setForm((current) => ({ ...current, [key]: event.target.value }));
  const ready = form.title.trim() && form.source_name.trim() && /^https?:\/\/\S+$/.test(form.source_url.trim()) && form.published_at;
  return <form className="news-add-form" onSubmit={(event) => { event.preventDefault(); onSubmit({ ...form, published_at: new Date(form.published_at).toISOString(), ticker: form.ticker?.trim() ? form.ticker.trim().toUpperCase() : null }); }}>
    <div className="news-add-grid">
      <label><span>Headline 標題</span><input value={form.title} onChange={set("title")} placeholder="Headline as it should read in the report" required /></label>
      <label><span>Publisher 來源</span><input value={form.source_name} onChange={set("source_name")} placeholder="e.g. Reuters" required /></label>
      <label><span>Article URL 連結</span><input type="url" value={form.source_url} onChange={set("source_url")} placeholder="https://…" required /></label>
      <label><span>Published 發布時間</span><input type="datetime-local" value={form.published_at} max={`${reportDate}T23:59`} onChange={set("published_at")} required /></label>
      <label><span>Ticker 代號</span><input value={form.ticker ?? ""} onChange={set("ticker")} placeholder="Optional, e.g. 0700.HK" /></label>
      <label className="news-add-wide"><span>Summary 摘要</span><textarea value={form.summary} onChange={set("summary")} placeholder="Short summary used in the report body" /></label>
    </div>
    <div className="news-add-actions"><button type="button" onClick={onCancel}>Cancel 取消</button><button type="submit" className="primary" disabled={busy || !ready}><Plus size={15} /> Add 新增</button></div>
  </form>;
}

export function NewsWorkbench({ report, busy, run, selectedSnapshot }: { report: Report; busy: boolean; run: RunAction; selectedSnapshot: SnapshotNews[] }) {
  const version = report.latest_document?.version ?? 1;
  const readOnly = report.status === "FINALIZED";
  const [candidates, setCandidates] = useState<NewsCandidate[]>([]);
  const [selected, setSelected] = useState<Draft[]>(() => draftsFromSnapshot(selectedSnapshot, report.report_date));
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("");
  const [site, setSite] = useState("");
  const [symbol, setSymbol] = useState("");
  const [providers, setProviders] = useState<NewsProvider[]>([]);
  const [sort, setSort] = useState<SortOrder>("newest");
  const [adding, setAdding] = useState(false);
  const [loading, setLoading] = useState(true);
  const initialWindow = reportNewsWindow(report.report_date);
  const [fromDate, setFromDate] = useState(initialWindow.fromDate);
  const [toDate, setToDate] = useState(initialWindow.toDate);
  const autoLoadKey = useRef<string | null>(null);
  const refreshProvider = providers.find((item) => item.key === "DA_REPORT" && item.configured)
    ?? providers.find((item) => item.default && item.configured)
    ?? providers.find((item) => item.configured);

  const load = () => api.listReportNewsCandidates(report.id).then(setCandidates);
  useEffect(() => { setLoading(true); load().catch(() => setCandidates([])).finally(() => setLoading(false)); }, [report.id, version]);
  useEffect(() => {
    // A provider without a credential in this environment cannot answer, so it is listed but not offered.
    api.listNewsProviders().then(setProviders).catch(() => setProviders([]));
  }, []);
  useEffect(() => {
    setSelected(draftsFromSnapshot(selectedSnapshot, report.report_date));
  }, [report.id, version]);

  useEffect(() => {
    const key = `${report.id}:${report.active_snapshot_id ?? "none"}`;
    const daConfigured = providers.some((item) => item.key === "DA_REPORT" && item.configured);
    if (!shouldAutoLoadDaNews({
      busy,
      candidateCount: candidates.length,
      daConfigured,
      loading,
      readOnly,
      attempted: autoLoadKey.current === key,
    })) return;
    autoLoadKey.current = key;
    void run(async () => {
      setLoading(true);
      try {
        const window = reportNewsWindow(report.report_date);
        const result = await api.fetchNewsCandidates(report.id, "CONSTITUENTS", window.fromDate, window.toDate, "DA_REPORT", true);
        setCandidates(result.items);
      } finally {
        setLoading(false);
      }
    });
  }, [busy, candidates.length, loading, providers, readOnly, report.active_snapshot_id, report.id, report.report_date, run]);

  const fetchFromProvider = (provider: string) => run(async () => { setLoading(true); try { await api.fetchNewsCandidates(report.id, "CONSTITUENTS", fromDate, toDate, provider); await load(); } finally { setLoading(false); } });
  const refresh = () => refreshProvider ? fetchFromProvider(refreshProvider.key) : Promise.resolve();
  const addManual = (item: NewsCandidateInput) => run(async () => { await api.addNewsCandidate(report.id, item); setAdding(false); await load(); });
  const sources = useMemo(() => [...new Set(candidates.map((item) => item.source_name))].sort(), [candidates]);
  const sites = useMemo(() => [...new Set(candidates.map((item) => item.site).filter(Boolean) as string[])].sort(), [candidates]);
  const symbols = useMemo(() => [...new Set(candidates.map((item) => item.ticker).filter(Boolean) as string[])].sort(), [candidates]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    // Keyword matching is AND across whitespace-separated terms so "apple revenue" narrows rather than widens.
    const terms = needle ? needle.split(/\s+/) : [];
    return candidates.filter((item) => {
      const text = `${item.title} ${item.summary} ${item.ticker ?? ""} ${item.source_name} ${item.site ?? ""}`.toLowerCase();
      const publishedDate = publishedDateHkt(item.published_at);
      return terms.every((term) => text.includes(term))
        && matchesNewsSource(item, source)
        && (!site || item.site === site)
        && (!symbol || item.ticker === symbol)
        && publishedDate >= fromDate && publishedDate <= toDate;
    }).sort((left, right) => sort === "newest" ? right.published_at.localeCompare(left.published_at) : left.published_at.localeCompare(right.published_at));
  }, [candidates, query, source, site, symbol, fromDate, toDate, sort]);

  const selectedIds = new Set(selected.map((item) => item.news_item_id));
  const toggle = (item: NewsCandidate) => setSelected((current) => toggleNewsSelection(current, item));
  const dragEnd = ({ active, over }: DragEndEvent) => { if (over && active.id !== over.id) setSelected((items) => arrayMove(items, items.findIndex((item) => item.news_item_id === active.id), items.findIndex((item) => item.news_item_id === over.id))); };
  const save = () => run(() => api.selectNews(report.id, version, selected.map((item, position) => ({ news_item_id: item.news_item_id, position, title_override: item.title_override, summary_override: item.summary_override }))));
  const resetFilters = () => { setQuery(""); setSource(""); setSite(""); setSymbol(""); setSort("newest"); };
  const filtered = Boolean(query || source || site || symbol);

  return <div className="news-workbench">
    <section className="news-column news-candidates">
      <header className="news-panel-head">
        <div className="news-panel-title"><h3>News &amp; Report</h3><span>新聞與報告</span></div>
        <div className="news-panel-count"><strong>{visible.length}</strong><small>of {candidates.length}</small></div>
        <button disabled={busy || readOnly || !refreshProvider} onClick={refresh} title={refreshProvider ? `Fetch ${refreshProvider.title} news for the selected date range` : "No news provider holds a credential in this environment"}><RefreshCw size={15} className={busy ? "spin" : ""} /> Refresh</button>
      </header>

      <div className="news-panel-filters">
        <button className="news-add-button" disabled={busy || readOnly} onClick={() => setAdding((open) => !open)}><Plus size={15} /> 添加新闻</button>
        <select value={source} onChange={(event) => setSource(event.target.value)} aria-label="Filter by source">
          <option value="">全部来源 All sources</option>
          {sources.map((item) => <option key={item}>{item}</option>)}
        </select>
        <select value={site} onChange={(event) => setSite(event.target.value)} aria-label="Filter by site"><option value="">全部站点 All sites</option>{sites.map((item) => <option key={item}>{item}</option>)}</select>
        <select value={symbol} onChange={(event) => setSymbol(event.target.value)} aria-label="Filter product news"><option value="">对应产品新闻 Product news</option>{symbols.map((item) => <option key={item}>{item}</option>)}</select>
        <label className="search-field"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="关键词 Keywords — headline, summary, ticker" aria-label="Search keywords" /></label>
        <div className="scope-control" role="group" aria-label="Sort order">
          <button className={sort === "newest" ? "active" : ""} onClick={() => setSort("newest")}>最新在前</button>
          <button className={sort === "oldest" ? "active" : ""} onClick={() => setSort("oldest")}>最舊在前</button>
        </div>
        <div className="news-date-range">
          <input type="date" value={fromDate} max={toDate} onChange={(event) => setFromDate(event.target.value)} aria-label="From date" />
          <span aria-hidden="true">→</span>
          <input type="date" value={toDate} min={fromDate} max={report.report_date} onChange={(event) => setToDate(event.target.value)} aria-label="To date" />
        </div>
        {filtered && <button className="news-reset" onClick={resetFilters}><X size={14} /> 清除筛选</button>}
      </div>

      {adding && <AddNewsForm reportDate={report.report_date} busy={busy} onCancel={() => setAdding(false)} onSubmit={addManual} />}

      <div className="news-list">
        {loading && <div className="skeleton-list" role="status" aria-label="Loading news candidates">{[0, 1, 2, 3].map((index) => <div className="skeleton skeleton-card" key={index} />)}</div>}
        {!loading && visible.map((item) => {
          const isSelected = selectedIds.has(item.id);
          return <article className={`news-item ${isSelected ? "selected" : ""}`} key={item.id}>
            <input type="checkbox" className="news-checkbox" checked={isSelected} disabled={readOnly} onChange={() => toggle(item)} aria-label={`Select ${item.title}`} />
            <div className="news-item-body">
              <h3>{item.title}</h3>
              {item.summary && <p>{item.summary}</p>}
              <footer>
                {item.ticker && <span className="news-chip ticker">{item.ticker}</span>}
                {item.provider === "MANUAL" && <span className="news-chip manual">手动添加 Manual</span>}
                {item.site && <span className="news-chip">{item.site}</span>}
                <span className="news-meta">{item.source_name}</span>
                <time dateTime={item.published_at}>{publishedLabel(item.published_at)}</time>
                <span className="news-chip tz">HKT</span>
                <a href={item.source_url} target="_blank" rel="noreferrer">Source <ExternalLink size={12} /></a>
              </footer>
            </div>
          </article>;
        })}
        {!loading && !visible.length && <div className="news-empty"><RefreshCw size={20} /><strong>{candidates.length ? "No news matches these filters" : "No matched company news"}</strong><span>{candidates.length ? "Clear the keyword or dropdown filters to see the rest." : "DA-Report loads automatically when a valid constituent snapshot is available; Refresh can retry the selected source."}</span></div>}
      </div>
    </section>

    <section className="news-column">
      <header className="news-panel-head">
        <div className="news-panel-title"><h3>Selected for report</h3><span>已選新聞</span></div>
        <div className="news-panel-count"><strong>{selected.length}</strong></div>
        <button className="primary" disabled={busy || readOnly || !selected.length} onClick={save}><Save size={15} /> Save</button>
      </header>
      <DndContext collisionDetection={closestCenter} onDragEnd={dragEnd}>
        <SortableContext items={selected.map((item) => item.news_item_id)} strategy={verticalListSortingStrategy}>
          <div className="news-list">
            {selected.map((item) => <SortableSelected key={item.news_item_id} item={item} disabled={readOnly} onUpdate={(next) => setSelected((items) => items.map((value) => value.news_item_id === next.news_item_id ? next : value))} onRemove={() => setSelected((items) => items.filter((value) => value.news_item_id !== item.news_item_id))} />)}
            {!selected.length && <div className="news-empty"><Check size={20} /><strong>No news selected</strong><span>Tick candidates on the left to build page 2.</span></div>}
          </div>
        </SortableContext>
      </DndContext>
    </section>
  </div>;
}
