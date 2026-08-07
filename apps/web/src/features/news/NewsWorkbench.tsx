import { useEffect, useState } from "react";
import { DndContext, closestCenter, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, arrayMove, verticalListSortingStrategy, useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Check, ExternalLink, GripVertical, RefreshCw, Save, Search, X } from "lucide-react";
import { api, type NewsCandidate, type NewsSelectionDraft, type Report } from "../../api";

type RunAction = (work: () => Promise<unknown>) => Promise<void>;
type SnapshotNews = Record<string, unknown>;

interface Draft extends NewsSelectionDraft { title: string; summary: string; source: string; publishedAt: string; ticker: string | null; }

function SortableSelected({ item, disabled, onUpdate, onRemove }: { item: Draft; disabled: boolean; onUpdate: (item: Draft) => void; onRemove: () => void }) {
  const sortable = useSortable({ id: item.news_item_id, disabled });
  return <article ref={sortable.setNodeRef} style={{ transform: CSS.Transform.toString(sortable.transform), transition: sortable.transition }} className="selected-news-card">
    <header><button className="icon-button news-drag-handle" title="Reorder news" {...sortable.attributes} {...sortable.listeners}><GripVertical size={17} /></button><span>{item.ticker ?? "General"}</span><button className="icon-button danger" title="Remove" onClick={onRemove}><X size={15} /></button></header>
    <input value={item.title} disabled={disabled} onChange={(event) => onUpdate({ ...item, title: event.target.value, title_override: event.target.value })} aria-label="Selected news title" />
    <textarea value={item.summary} disabled={disabled} onChange={(event) => onUpdate({ ...item, summary: event.target.value, summary_override: event.target.value })} aria-label="Selected news summary" />
    <footer>{item.source} · {new Date(item.publishedAt).toLocaleDateString("en-HK")}</footer>
  </article>;
}

export function NewsWorkbench({ report, busy, run, selectedSnapshot }: { report: Report; busy: boolean; run: RunAction; selectedSnapshot: SnapshotNews[] }) {
  const version = report.latest_document?.version ?? 1;
  const [candidates, setCandidates] = useState<NewsCandidate[]>([]);
  const [selected, setSelected] = useState<Draft[]>([]);
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("");
  const [symbol, setSymbol] = useState("");
  const [importance, setImportance] = useState("");
  const [scope, setScope] = useState<"CONSTITUENTS" | "GENERAL">("CONSTITUENTS");
  const [sort, setSort] = useState<"time" | "importance">("time");
  const [fromDate, setFromDate] = useState(`${report.report_date.slice(0, 8)}01`);
  const [toDate, setToDate] = useState(report.report_date);
  const frozenSnapshot = selectedSnapshot.filter((item) => !item.news_item_id);

  const load = () => api.listReportNewsCandidates(report.id).then(setCandidates);
  useEffect(() => { load().catch(() => setCandidates([])); }, [report.id, version]);
  useEffect(() => {
    const fromDocument = selectedSnapshot.filter((item) => item.news_item_id).map((item, index) => ({
      news_item_id: String(item.news_item_id), position: index, title: String(item.title ?? ""), summary: String(item.summary ?? ""),
      source: String(item.source_name ?? ""), publishedAt: String(item.published_at ?? report.report_date), ticker: String(item.ticker ?? "") || null,
      title_override: String(item.title ?? ""), summary_override: String(item.summary ?? ""),
    }));
    if (fromDocument.length) setSelected(fromDocument);
  }, [version]);

  const refresh = () => run(async () => { await api.fetchNewsCandidates(report.id, scope, fromDate, toDate); await load(); });
  const sources = [...new Set(candidates.map((item) => item.source_name))].sort();
  const symbols = [...new Set(candidates.map((item) => item.ticker).filter(Boolean) as string[])].sort();
  const rank = { HIGH: 3, MEDIUM: 2, LOW: 1 };
  const visible = candidates.filter((item) => {
    const text = `${item.title} ${item.summary} ${item.ticker ?? ""}`.toLowerCase();
    const publishedDate = item.published_at.slice(0, 10);
    return text.includes(query.toLowerCase()) && (!source || item.source_name === source) && (!symbol || item.ticker === symbol) && (!importance || item.importance === importance) && publishedDate >= fromDate && publishedDate <= toDate;
  }).sort((left, right) => sort === "importance" ? rank[right.importance] - rank[left.importance] : right.published_at.localeCompare(left.published_at));
  const selectedIds = new Set(selected.map((item) => item.news_item_id));
  const add = (item: NewsCandidate) => setSelected((current) => [...current, { news_item_id: item.id, position: current.length, title: item.title, summary: item.summary, source: item.source_name, publishedAt: item.published_at, ticker: item.ticker }]);
  const dragEnd = ({ active, over }: DragEndEvent) => { if (over && active.id !== over.id) setSelected((items) => arrayMove(items, items.findIndex((item) => item.news_item_id === active.id), items.findIndex((item) => item.news_item_id === over.id))); };
  const save = () => run(() => api.selectNews(report.id, version, selected.map((item, position) => ({ news_item_id: item.news_item_id, position, title_override: item.title_override, summary_override: item.summary_override }))));

  return <>
    <div className="news-filterbar">
      <label className="search-field"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search headline, company or ticker" /></label>
      <select value={source} onChange={(event) => setSource(event.target.value)}><option value="">All sources</option>{sources.map((item) => <option key={item}>{item}</option>)}</select>
      <select value={symbol} onChange={(event) => setSymbol(event.target.value)}><option value="">All companies</option>{symbols.map((item) => <option key={item}>{item}</option>)}</select>
      <select value={importance} onChange={(event) => setImportance(event.target.value)}><option value="">All importance</option><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select>
      <select value={sort} onChange={(event) => setSort(event.target.value as "time" | "importance")}><option value="time">Time order</option><option value="importance">Importance</option></select>
      <label className="date-field"><span>From</span><input type="date" value={fromDate} max={toDate} onChange={(event) => setFromDate(event.target.value)} /></label>
      <label className="date-field"><span>To</span><input type="date" value={toDate} min={fromDate} max={report.report_date} onChange={(event) => setToDate(event.target.value)} /></label>
      <div className="scope-control"><button className={scope === "CONSTITUENTS" ? "active" : ""} onClick={() => setScope("CONSTITUENTS")}>Constituents</button><button className={scope === "GENERAL" ? "active" : ""} onClick={() => setScope("GENERAL")}>General</button></div>
      <button disabled={busy || report.status === "FINALIZED"} onClick={refresh}><RefreshCw size={16} /> Refresh</button>
    </div>
    <div className="news-workbench">
      <section className="news-column"><div className="surface-heading"><div><span>Candidate library</span><strong>{visible.length}</strong></div></div><div className="news-list">{visible.map((item) => <article className={`news-item ${selectedIds.has(item.id) ? "selected" : ""}`} key={item.id}><div><button className="news-checkbox" disabled={selectedIds.has(item.id)} onClick={() => add(item)}>{selectedIds.has(item.id) ? <Check size={14} /> : null}</button><span className={`importance ${item.importance.toLowerCase()}`}>{item.importance}</span><time>{new Date(item.published_at).toLocaleString("en-HK", { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</time></div><h3>{item.title}</h3><p>{item.summary}</p><footer><span>{item.ticker ?? "General"} · {item.source_name}</span><a href={item.source_url} target="_blank" rel="noreferrer">Source <ExternalLink size={12} /></a></footer></article>)}{!visible.length && <div className="news-empty"><RefreshCw size={20} /><strong>No candidates loaded</strong><span>Select a scope and refresh FMP news for this report.</span></div>}</div></section>
      <section className="news-column"><div className="surface-heading"><div><span>Selected for report</span><strong>{frozenSnapshot.length + selected.length}</strong></div><button className="primary" disabled={busy || report.status === "FINALIZED" || !selected.length} onClick={save}><Save size={16} /> Save</button></div><DndContext collisionDetection={closestCenter} onDragEnd={dragEnd}><SortableContext items={selected.map((item) => item.news_item_id)} strategy={verticalListSortingStrategy}><div className="news-list">{frozenSnapshot.map((item, index) => <article className="selected-news-card frozen" key={`${String(item.title)}-${index}`}><header><span>Existing report snapshot</span></header><strong>{String(item.title ?? "")}</strong><p>{String(item.summary ?? "")}</p></article>)}{selected.map((item) => <SortableSelected key={item.news_item_id} item={item} disabled={report.status === "FINALIZED"} onUpdate={(next) => setSelected((items) => items.map((value) => value.news_item_id === next.news_item_id ? next : value))} onRemove={() => setSelected((items) => items.filter((value) => value.news_item_id !== item.news_item_id))} />)}{!frozenSnapshot.length && !selected.length && <div className="news-empty"><Check size={20} /><strong>No news selected</strong><span>Add candidates from the library to build page 2.</span></div>}</div></SortableContext></DndContext></section>
    </div>
  </>;
}