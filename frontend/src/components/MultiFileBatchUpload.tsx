import { useRef, useState, type DragEvent } from "react";
import { AlertTriangle, Check, FileStack, Trash2, X } from "lucide-react";
import { api, type ClearableDatasetType, type ImportBatch, type Report } from "../api";

type RunAction = (work: () => Promise<unknown>) => Promise<void>;
type PreviewRow = ImportBatch["merge_preview"]["rows"][number];

function twoDecimals(value: string | number | null): string {
  if (value === null || value === "") return "N/A";
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(2) : "N/A";
}

function percentagePoints(value: string | number | null): string {
  if (value === null || value === "") return "N/A";
  const numeric = Number(value);
  return Number.isFinite(numeric) ? (numeric * 100).toFixed(2) : "N/A";
}

function previewName(row: PreviewRow): string {
  return row.name_en?.trim() || row.name_zh_hant?.trim() || "N/A";
}

export function MultiFileBatchUpload({ report, busy, run, hasCurrentData }: {
  report: Report;
  busy: boolean;
  run: RunAction;
  hasCurrentData: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [batch, setBatch] = useState<ImportBatch | null>(null);
  const [reason, setReason] = useState("");
  const [dragging, setDragging] = useState(false);
  const [confirmingClear, setConfirmingClear] = useState(false);

  const upload = (files: File[]) => {
    if (!files.length) return;
    void run(async () => {
      setBatch(await api.uploadImportBatch(report.id, files));
      setReason("");
    });
  };
  const drop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    upload(Array.from(event.dataTransfer.files));
  };
  const exclude = (importId: string) => run(async () => {
    if (batch) setBatch(await api.excludeImportBatchFile(report.id, batch.id, importId));
  });
  const discard = () => run(async () => {
    if (!batch) return;
    await api.discardImportBatch(report.id, batch.id);
    setBatch(null);
    setReason("");
  });
  const apply = () => run(async () => {
    if (!batch) return;
    await api.applyImportBatch(report.id, batch.id, report.version, hasCurrentData ? reason.trim() : undefined);
    setBatch(null);
    setReason("");
  });
  const clearCurrentData = () => run(async () => {
    const clearable = new Set<ClearableDatasetType>(["constituent_performance", "constituent_returns", "index_constituents"]);
    const slots = await api.listDatasets(report.id);
    const applied = new Set(slots
      .filter((slot) => slot.state === "APPLIED" && clearable.has(slot.key as ClearableDatasetType))
      .map((slot) => slot.key as ClearableDatasetType));
    const sequence: ClearableDatasetType[] = applied.has("constituent_performance")
      ? ["constituent_performance"]
      : (["constituent_returns", "index_constituents"] as ClearableDatasetType[]).filter((datasetType) => applied.has(datasetType));
    let version = report.version;
    for (const [index, datasetType] of sequence.entries()) {
      await api.clearDataset(report.id, datasetType, version);
      if (index < sequence.length - 1) {
        version = (await api.getReport(report.id)).version;
      }
    }
    setBatch(null);
    setReason("");
    setConfirmingClear(false);
  });
  const canApply = Boolean(batch && ["READY", "PARTIAL_READY"].includes(batch.status) && (!batch.requires_reason || reason.trim().length >= 5));
  const identityRows = batch?.files.find((file) => file.status === "VALIDATED" && ["index_constituents", "constituent_performance"].includes(file.detected_type))?.row_count ?? 0;
  const mergePreview = batch?.merge_preview;

  return <section className="batch-import" aria-label="Constituent multi-file import">
    <div className="batch-flow" aria-label="Import workflow">
      <span>1 Upload</span><span>2 Auto-detect</span><span>3 Merge preview</span><span>4 Apply once</span><span>5 Auto-calculate</span>
    </div>
    <div
      className={`batch-dropzone${dragging ? " is-dragging" : ""}`}
      onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={() => setDragging(false)}
      onDrop={drop}
    >
      <FileStack size={24} />
      <div><strong>Upload required Page 04 data</strong><span>Current report: {report.report_date}. Provide files from this report month; nothing is analysed until the validated batch is explicitly applied.</span></div>
      <button disabled={busy || report.status === "FINALIZED"} onClick={() => inputRef.current?.click()}>Choose files</button>
      <input ref={inputRef} type="file" multiple hidden onChange={(event) => { upload(Array.from(event.target.files ?? [])); event.currentTarget.value = ""; }} />
    </div>
    {hasCurrentData && <div className="batch-current-data-actions">
      {!confirmingClear
        ? <button className="danger-button" disabled={busy || report.status === "FINALIZED" || Boolean(batch)} onClick={() => setConfirmingClear(true)}><Trash2 size={16} /> Delete current Page 04 data</button>
        : <div className="batch-clear-confirmation" role="alert">
          <div><strong>Delete the current Page 04 data?</strong><span>The active report will be cleared for a fresh upload. Historical snapshots and audit records will remain available.</span></div>
          <div><button className="danger-button" disabled={busy} onClick={clearCurrentData}><Trash2 size={16} /> Yes, delete current data</button><button disabled={busy} onClick={() => setConfirmingClear(false)}>Cancel</button></div>
        </div>}
    </div>}
    {batch && <div className={`batch-review batch-${batch.status.toLowerCase()}`}>
      <header><div><strong>{batch.status === "READY" ? "Batch ready to apply" : batch.status === "PARTIAL_READY" ? "Identity data ready to save" : batch.status.replaceAll("_", " ")}</strong><span>{batch.status === "PARTIAL_READY" ? `${identityRows} constituent rows can be saved now; returns will display as N/A until added later.` : batch.status === "INCOMPLETE" && batch.coverage.returns?.state === "READY" ? "A constituent identity file is required before these returns can be saved." : `${batch.files.length} files inspected`}</span></div><span className="dataset-state">{batch.status.replaceAll("_", " ")}</span></header>
      <div className="batch-coverage">
        <span className={batch.coverage.identity?.state === "READY" ? "is-ready" : ""}>Identity / price / weight: {batch.coverage.identity?.state ?? "MISSING"}</span>
        <span className={batch.coverage.returns?.state === "READY" ? "is-ready" : ""}>1M / 3M / 6M / YTD: {batch.coverage.returns?.state ?? "MISSING"}</span>
      </div>
      <div className="batch-files">{batch.files.map((file) => <article key={file.id}>
        <div><strong>{file.filename}</strong><span>{file.detected_type.replaceAll("_", " ")} · {file.row_count} rows · {file.status === "UNSUPPORTED" ? "SKIPPED" : file.status}</span>{file.errors.map((finding, index) => <small key={`${finding.error_code}-${index}`}><AlertTriangle size={13} /> {finding.message ?? finding.fix_hint ?? finding.error_code}</small>)}</div>
        {!(["APPLIED", "EXCLUDED"].includes(file.status)) && <button className="icon-button danger" title="Exclude this file" disabled={busy} onClick={() => void exclude(file.id)}><X size={16} /></button>}
      </article>)}</div>
      {batch.errors.length > 0 && <ul className="batch-errors">{batch.errors.map((finding, index) => <li key={`${finding.error_code}-${index}`}><AlertTriangle size={14} /> {finding.message} {finding.fix_hint}</li>)}</ul>}
      {mergePreview && (mergePreview.rows.length > 0 || mergePreview.unmatched_return_codes.length > 0) && <section className="batch-merge-preview" aria-label="Merged constituent preview">
        <header>
          <div><strong>Merged Page 04 preview</strong><span>{mergePreview.report_month ? `Report month ${mergePreview.report_month}` : "Report month unavailable"}{mergePreview.as_of_date ? ` · As of ${mergePreview.as_of_date}` : ""}</span></div>
          <span>{mergePreview.rows.length} constituents</span>
        </header>
        {mergePreview.sources.length > 0 && <p>Sources: {mergePreview.sources.map((source) => source.filename).join(" · ")}</p>}
        <div className="data-surface constituent-table">
          <table>
            <thead><tr><th>Stock Code</th><th>Stock Name</th><th>Closing Price (HKD)</th><th>Weighting (%)</th><th>1-month return (%)</th><th>3-month return (%)</th><th>6-month return (%)</th><th>YTD return (%)</th></tr></thead>
            <tbody>{mergePreview.rows.map((row) => <tr key={row.security_code}><th scope="row"><span className="security-code">{row.security_code}</span></th><td><strong>{previewName(row)}</strong></td><td>{twoDecimals(row.close_price)}</td><td>{percentagePoints(row.weight)}</td><td>{percentagePoints(row.return_1m)}</td><td>{percentagePoints(row.return_3m)}</td><td>{percentagePoints(row.return_6m)}</td><td>{percentagePoints(row.return_ytd)}</td></tr>)}</tbody>
          </table>
        </div>
        {(mergePreview.unmatched_identity_codes.length > 0 || mergePreview.unmatched_return_codes.length > 0) && <div className="batch-match-findings" role="status">
          <AlertTriangle size={16} />
          <div>
            {mergePreview.unmatched_identity_codes.length > 0 && <span>No matching return row: {mergePreview.unmatched_identity_codes.join(", ")} (displayed as N/A)</span>}
            {mergePreview.unmatched_return_codes.length > 0 && <span>Return rows outside the constituent file: {mergePreview.unmatched_return_codes.join(", ")} (not merged)</span>}
          </div>
        </div>}
      </section>}
      <footer>
        {["READY", "PARTIAL_READY"].includes(batch.status) && batch.requires_reason && <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Replacement reason" aria-label="Replacement reason" />}
        <button className="primary" disabled={busy || !canApply} onClick={apply}><Check size={16} /> {batch.status === "PARTIAL_READY" ? "Save available data" : "Apply batch once"}</button>
        <button className="danger-button" disabled={busy} onClick={discard}><Trash2 size={16} /> Discard batch</button>
      </footer>
    </div>}
  </section>;
}
