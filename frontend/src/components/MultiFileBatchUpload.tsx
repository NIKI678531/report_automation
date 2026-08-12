import { useRef, useState, type DragEvent } from "react";
import { AlertTriangle, Check, FileStack, Trash2, X } from "lucide-react";
import { api, type ImportBatch, type Report } from "../api";

type RunAction = (work: () => Promise<unknown>) => Promise<void>;

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
  const canApply = batch?.status === "READY" && (!hasCurrentData || reason.trim().length >= 5);
  const identityRows = batch?.files.find((file) => file.status === "VALIDATED" && ["index_constituents", "constituent_performance"].includes(file.detected_type))?.row_count ?? 0;

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
      <div><strong>Drop any files here</strong><span>Known CSV/XLSX/XLSM layouts are combined; unrelated files are safely skipped. Up to 20 files, 100 MB total.</span></div>
      <button disabled={busy || report.status === "FINALIZED"} onClick={() => inputRef.current?.click()}>Choose files</button>
      <input ref={inputRef} type="file" multiple hidden onChange={(event) => { upload(Array.from(event.target.files ?? [])); event.currentTarget.value = ""; }} />
    </div>
    {batch && <div className={`batch-review batch-${batch.status.toLowerCase()}`}>
      <header><div><strong>{batch.status === "READY" ? "Batch ready to apply" : batch.status.replaceAll("_", " ")}</strong><span>{batch.status === "INCOMPLETE" && identityRows ? `${identityRows} constituent rows validated; a return file is still required.` : `${batch.files.length} files inspected`}</span></div><span className="dataset-state">{batch.status}</span></header>
      <div className="batch-coverage">
        <span className={batch.coverage.identity?.state === "READY" ? "is-ready" : ""}>Identity / price / weight: {batch.coverage.identity?.state ?? "MISSING"}</span>
        <span className={batch.coverage.returns?.state === "READY" ? "is-ready" : ""}>1M / 3M / 6M / YTD: {batch.coverage.returns?.state ?? "MISSING"}</span>
      </div>
      <div className="batch-files">{batch.files.map((file) => <article key={file.id}>
        <div><strong>{file.filename}</strong><span>{file.detected_type.replaceAll("_", " ")} · {file.row_count} rows · {file.status === "UNSUPPORTED" ? "SKIPPED" : file.status}</span>{file.errors.map((finding, index) => <small key={`${finding.error_code}-${index}`}><AlertTriangle size={13} /> {finding.message ?? finding.fix_hint ?? finding.error_code}</small>)}</div>
        {!(["APPLIED", "EXCLUDED"].includes(file.status)) && <button className="icon-button danger" title="Exclude this file" disabled={busy} onClick={() => void exclude(file.id)}><X size={16} /></button>}
      </article>)}</div>
      {batch.errors.length > 0 && <ul className="batch-errors">{batch.errors.map((finding, index) => <li key={`${finding.error_code}-${index}`}><AlertTriangle size={14} /> {finding.message} {finding.fix_hint}</li>)}</ul>}
      <footer>
        {batch.status === "READY" && hasCurrentData && <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Replacement reason" aria-label="Replacement reason" />}
        <button className="primary" disabled={busy || !canApply} onClick={apply}><Check size={16} /> Apply batch once</button>
        <button className="danger-button" disabled={busy} onClick={discard}><Trash2 size={16} /> Discard batch</button>
      </footer>
    </div>}
  </section>;
}
