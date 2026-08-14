import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Check, Upload } from "lucide-react";
import { api, type DatasetSlot, type DatasetType, type ImportResult, type Report } from "../api";

type RunAction = (work: () => Promise<unknown>) => Promise<void>;

export function DatasetUploadSlot({ report, datasetType, busy, run }: {
  report: Report;
  datasetType: DatasetType;
  busy: boolean;
  run: RunAction;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [slot, setSlot] = useState<DatasetSlot | null>(null);
  const [candidate, setCandidate] = useState<ImportResult | null>(null);
  const [reason, setReason] = useState("");

  useEffect(() => {
    api.listDatasets(report.id)
      .then((items) => setSlot(items.find((item) => item.key === datasetType) ?? null))
      .catch(() => setSlot(null));
  }, [report.id, report.active_snapshot_id, report.version, datasetType]);

  const upload = (file?: File) => {
    if (!file) return;
    void run(async () => {
      setCandidate(await api.uploadDataset(report.id, datasetType, file));
      setReason("");
    });
  };
  const apply = () => run(async () => {
    if (!candidate) return;
    await api.applyImport(report.id, candidate.id, candidate.requires_reason ? reason.trim() : undefined);
    setCandidate(null);
    setReason("");
  });
  const state = candidate?.status ?? slot?.state ?? "MISSING";
  const canApply = candidate?.status === "VALIDATED" && (!candidate.requires_reason || reason.trim().length >= 5);
  const findings = candidate?.validation_results.filter((item) => item.status !== "PASSED") ?? [];

  return <section className="dataset-upload" aria-label={`${slot?.title ?? datasetType} data slot`}>
    <div className="dataset-slot-head">
      <div>
        <strong>{slot?.title ?? "Total Return series"}</strong>
        <span>{slot?.description ?? "Official FUND and BENCHMARK Total Return observations."}</span>
      </div>
      <span className={`dataset-state state-${state.toLowerCase()}`}>{state.replaceAll("_", " ")}</span>
    </div>
    <p className="dataset-current">
      {slot?.state === "APPLIED"
        ? `${slot.filename ?? "Approved source"} · ${slot.rows} observations`
        : "Required CSV columns: instrument_role, instrument_code, trade_date, total_return_value, series_type, currency, source."}
    </p>
    <div className="dataset-actions">
      <button disabled={busy || report.status === "FINALIZED"} onClick={() => inputRef.current?.click()}>
        <Upload size={16} /> Upload Bloomberg CSV
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".csv,text/csv"
        hidden
        onChange={(event) => { upload(event.target.files?.[0]); event.currentTarget.value = ""; }}
      />
    </div>
    {candidate && <div className={`import-review import-${candidate.status.toLowerCase()}`}>
      <div className="import-summary">
        <strong>{candidate.status === "VALIDATED" ? "File validated" : "File needs attention"}</strong>
        <span>{candidate.summary.rows_parsed} observations · {candidate.summary.blocking} blocking · {candidate.summary.warnings} warnings</span>
        {findings.length > 0 && <ul>{findings.map((finding, index) => <li key={`${finding.error_code ?? finding.check_id}-${index}`}><AlertTriangle size={14} /> {finding.message ?? finding.fix_hint}</li>)}</ul>}
      </div>
      {candidate.status === "VALIDATED" && <div className="import-apply">
        {candidate.requires_reason && <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Replacement reason" aria-label="Replacement reason" />}
        <button className="primary" disabled={busy || !canApply} onClick={apply}><Check size={16} /> Apply data</button>
      </div>}
    </div>}
  </section>;
}
