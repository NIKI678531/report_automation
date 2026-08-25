import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Check, Upload } from "lucide-react";
import { api, type DatasetSlot, type DatasetType, type ImportResult, type Report } from "../api";
import { useLocale } from "../i18n";

type RunAction = (work: () => Promise<unknown>) => Promise<void>;

export function DatasetUploadSlot({ report, datasetType, busy, run }: {
  report: Report;
  datasetType: DatasetType;
  busy: boolean;
  run: RunAction;
}) {
  const { t, statusLabel } = useLocale();
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

  return <section className="dataset-upload" aria-label={t("dataImport", { name: slot?.title ?? datasetType })}>
    <div className="dataset-slot-head">
      <div>
        <strong>{slot?.title ?? t("totalReturnSeries")}</strong>
        <span>{slot?.description ?? t("totalReturnHelp")}</span>
      </div>
      <span className={`dataset-state state-${state.toLowerCase()}`}>{statusLabel(state)}</span>
    </div>
    <p className="dataset-current">
      {slot?.state === "APPLIED"
        ? `${slot.filename ?? t("approvedSource")} · ${t("observations", { rows: slot.rows })}`
        : t("requiredCsv")}
    </p>
    <div className="dataset-actions">
      <button disabled={busy || report.status === "FINALIZED"} onClick={() => inputRef.current?.click()}>
        <Upload size={16} /> {t("uploadBloomberg")}
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
        <strong>{candidate.status === "VALIDATED" ? t("fileValidated") : t("fileNeedsAttention")}</strong>
        <span>{t("observations", { rows: candidate.summary.rows_parsed })} · {t("blockingWarnings", { blocking: candidate.summary.blocking, warnings: candidate.summary.warnings })}</span>
        {findings.length > 0 && <ul>{findings.map((finding, index) => <li key={`${finding.error_code ?? finding.check_id}-${index}`}><AlertTriangle size={14} /> {finding.message ?? finding.fix_hint}</li>)}</ul>}
      </div>
      {candidate.status === "VALIDATED" && <div className="import-apply">
        {candidate.requires_reason && <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder={t("replacementReason")} aria-label={t("replacementReason")} />}
        <button className="primary" disabled={busy || !canApply} onClick={apply}><Check size={16} /> {t("applyData")}</button>
      </div>}
    </div>}
  </section>;
}
