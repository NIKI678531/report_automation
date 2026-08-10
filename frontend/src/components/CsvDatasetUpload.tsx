import { useRef, useState } from "react";
import { Check, Download, FileUp } from "lucide-react";
import { api, type DatasetType, type Report } from "../api";

type RunAction = (work: () => Promise<unknown>) => Promise<void>;

const templates: Record<DatasetType, string> = {
  constituents: "security_code,ticker,name_en,name_zh_hant,close_price,currency,weight,sector,return_1m,return_3m,return_6m,return_ytd\n",
  historical_performance: "instrument_role,instrument_code,trade_date,total_return_value,series_type,currency,source\n",
  final_analytics: "record_type,as_of_date,security_code,ticker,name_en,name_zh_hant,close_price,currency,value_scale,weight,sector,return_1m,return_3m,return_6m,return_ytd,metric_code,metric_date,value,unit,source,market,calendar_date,is_trading_day,index_code,event_type,announcement_date,effective_date\n",
};

export function CsvDatasetUpload({ report, datasetType, busy, run, recalculateAfterApply = false }: {
  report: Report;
  datasetType: DatasetType;
  busy: boolean;
  run: RunAction;
  recalculateAfterApply?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [importId, setImportId] = useState("");
  const [summary, setSummary] = useState("");
  const [reason, setReason] = useState("");

  const downloadTemplate = () => {
    const url = URL.createObjectURL(new Blob([templates[datasetType]], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${datasetType}-template.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const upload = (file: File) => run(async () => {
    const result = await api.uploadDataset(report.id, datasetType, file);
    setImportId(result.id);
    setSummary(Object.entries(result.diff.summary).map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`).join(" · "));
  });

  const apply = () => run(async () => {
    await api.applyImport(report.id, importId, reason);
    if (recalculateAfterApply) await api.calculate(report.id);
    setImportId("");
    setSummary("");
    setReason("");
  });

  return <section className="dataset-upload" aria-label={`${datasetType} CSV import`}>
    <div className="dataset-actions">
      <button disabled={busy || report.status === "FINALIZED"} onClick={() => inputRef.current?.click()}><FileUp size={16} /> Upload CSV</button>
      <button className="quiet-button" onClick={downloadTemplate}><Download size={16} /> Template</button>
      <input ref={inputRef} type="file" accept=".csv,text/csv" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) upload(file); event.currentTarget.value = ""; }} />
    </div>
    {importId && <div className="import-review"><div><strong>Validated CSV</strong><span>{summary || "No differences detected"}</span></div><input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Approved override reason" /><button className="primary" disabled={busy || reason.trim().length < 5} onClick={apply}><Check size={16} /> Apply new snapshot</button></div>}
  </section>;
}