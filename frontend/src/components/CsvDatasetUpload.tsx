import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Check, Download, FileUp } from "lucide-react";
import { api, type DatasetSlot, type DatasetType, type ImportResult, type Report } from "../api";

type RunAction = (work: () => Promise<unknown>) => Promise<void>;

const templates: Record<DatasetType, string> = {
  index_constituents: "Prod Dt,Tradate,Idx Cde,Lcal Cde,Stk Name_E,Stk Name_TC,Cls Price,Lcal Ccy,Pct Idx Wgt,Industry,Sector\n",
  constituent_returns: "security_code,name_en,period_end,period_start_1m,return_1m,period_start_3m,return_3m,period_start_6m,return_6m,period_start_ytd,return_ytd,source\n",
  total_return_series: "instrument_role,instrument_code,trade_date,total_return_value,series_type,currency,source\n",
  fund_kpi_daily: "metric_code,metric_date,value,unit,currency,source\n",
  trading_calendar: "market,date,is_trading_day,source\n",
  index_events: "index_code,event_type,announcement_date,effective_date,source\n",
};

export function needsReplacementReason(slot: DatasetSlot | null): boolean {
  return slot?.state === "APPLIED";
}

export function CsvDatasetUpload({ report, datasetType, busy, run }: {
  report: Report;
  datasetType: DatasetType;
  busy: boolean;
  run: RunAction;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [slot, setSlot] = useState<DatasetSlot | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [reason, setReason] = useState("");

  const loadSlot = () => api.listDatasets(report.id).then((items) => {
    setSlot(items.find((item) => item.key === datasetType) ?? null);
  });

  useEffect(() => {
    void loadSlot();
  }, [report.id, report.active_snapshot_id, datasetType]);

  const downloadTemplate = () => {
    const url = URL.createObjectURL(new Blob([templates[datasetType]], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${datasetType}-template.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const upload = (file: File) => run(async () => {
    const uploaded = await api.uploadDataset(report.id, datasetType, file);
    setResult(uploaded);
    setReason("");
  });

  const replacement = result?.requires_reason ?? needsReplacementReason(slot);
  const canApply = result?.status === "VALIDATED" && (!replacement || reason.trim().length >= 5);
  const apply = () => run(async () => {
    if (!result) return;
    await api.applyImport(report.id, result.id, replacement ? reason.trim() : undefined);
    setResult(null);
    setReason("");
    await loadSlot();
  });
  const summary = result
    ? Object.entries(result.diff.summary).map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`).join(" · ")
    : "";
  const accepts = slot?.accepts.join(",") || ".csv,.xlsx,.xlsm";

  return <section className="dataset-upload" aria-label={`${datasetType} data import`}>
    <div className="dataset-slot-head">
      <div><strong>{slot?.title ?? datasetType.replaceAll("_", " ")}</strong><span>{slot?.description}</span></div>
      <span className={`dataset-state state-${(slot?.state ?? "MISSING").toLowerCase()}`}>{slot?.state ?? "MISSING"}</span>
    </div>
    {slot?.filename && <p className="dataset-current">Current: {slot.filename} · {slot.rows} rows</p>}
    <div className="dataset-actions">
      <button disabled={busy || report.status === "FINALIZED"} onClick={() => inputRef.current?.click()}><FileUp size={16} /> Upload file</button>
      <button className="quiet-button" onClick={downloadTemplate}><Download size={16} /> Template</button>
      <input ref={inputRef} type="file" accept={accepts} hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); event.currentTarget.value = ""; }} />
    </div>
    {result && <div className={`import-review import-${result.status.toLowerCase()}`}>
      <div className="import-summary">
        <strong>{result.status === "VALIDATED" ? "File validated" : result.status.replaceAll("_", " ")}</strong>
        <span>{summary || `${result.summary.rows_parsed} rows parsed`}</span>
        {result.validation_results.length > 0 && <ul>{result.validation_results.map((finding, index) => <li key={`${finding.error_code ?? finding.check_id}-${index}`}><AlertTriangle size={14} /><span>{finding.message ?? finding.fix_hint ?? finding.error_code ?? finding.check_id}</span></li>)}</ul>}
      </div>
      {result.status === "VALIDATED" && <div className="import-apply">
        {replacement && <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Replacement reason" aria-label="Replacement reason" />}
        <button className="primary" disabled={busy || !canApply} onClick={apply}><Check size={16} /> {replacement ? "Replace current data" : "Use this data"}</button>
      </div>}
    </div>}
  </section>;
}