import { useEffect, useRef, useState } from "react";
import { Languages, RefreshCw } from "lucide-react";
import { ApiError, api, type Report, type TranslationJob } from "../../api";
import { useLocale } from "../../i18n";
import { isReportReadOnly } from "../../reportModules";

interface Props {
  report: Report;
  automaticSource?: string;
  onConsumed: () => void;
  onBusyChange: (busy: boolean) => void;
  prepare: () => Promise<Report | null>;
  apply: () => Promise<boolean>;
}

export function TranslationStatus({ report, automaticSource, onConsumed, onBusyChange, prepare, apply }: Props) {
  const { t } = useLocale();
  const [job, setJob] = useState<TranslationJob | null>(null);
  const [submitting, setSubmitting] = useState(Boolean(automaticSource && report.translation_enabled));
  const [error, setError] = useState("");
  const [newVersion, setNewVersion] = useState(false);
  const [offlineComplete, setOfflineComplete] = useState(false);
  const offline = !automaticSource && ["ZH_HANS", "ZH_HANT"].includes(report.language_mode) && ["ZH_HANS", "ZH_HANT"].includes(report.translation_source_language_mode ?? "");
  const mounted = useRef(true);
  const pending = submitting || job?.status === "QUEUED" || job?.status === "RUNNING";
  const sourceId = job?.source_report_id ?? automaticSource ?? report.translation_source_report_id;

  function failure(caught: unknown): string {
    return caught instanceof ApiError ? `${t("translationFailed")} ${caught.errorCode ?? ""}${caught.requestId ? ` (${caught.requestId})` : ""}` : t("translationFailed");
  }

  useEffect(() => {
    onBusyChange(pending);
    return () => onBusyChange(false);
  }, [pending, onBusyChange]);

  useEffect(() => {
    let active = true;
    mounted.current = true;
    if (automaticSource) onConsumed();
    const timer = window.setTimeout(() => {
      if (!report.translation_enabled) { setSubmitting(false); return; }
      void (async () => {
        try {
          if (automaticSource && !isReportReadOnly(report)) {
            const source = await api.getReport(automaticSource);
            if (!active) return;
            const next = await api.translateReport(source.id, report.id, source.latest_document?.version ?? 1, report.latest_document?.version ?? 1, `auto:${source.id}:${source.latest_document?.version}:${report.latest_document?.version}`);
            if (active) setJob(next);
          } else {
            const previous = await api.latestTranslation(report.id);
            if (active) setJob(previous);
          }
        } catch (caught) { if (active) setError(failure(caught)); }
        finally { if (active) setSubmitting(false); }
      })();
    }, 0);
    return () => { active = false; mounted.current = false; window.clearTimeout(timer); };
  }, [report.id]);

  useEffect(() => {
    if (!job) return;
    let active = true;
    let timer: number;
    const poll = async () => {
      try {
        const next = await api.getTranslationJob(report.id, job.id);
        if (!active) return;
        setJob(next);
        if (next.status === "QUEUED" || next.status === "RUNNING") timer = window.setTimeout(() => void poll(), 1000);
      } catch (caught) {
        if (active) { setError(failure(caught)); setJob({ ...job, status: "FAILED" }); }
      }
    };
    if (job.status === "QUEUED" || job.status === "RUNNING") timer = window.setTimeout(() => void poll(), 500);
    else if (job.status === "SUCCEEDED" && (job.result_document_version ?? 0) > (report.latest_document?.version ?? 0)) {
      void apply().then((applied) => { if (active) setNewVersion(!applied); }).catch((caught) => { if (active) setError(failure(caught)); });
    }
    return () => { active = false; window.clearTimeout(timer); };
  }, [job?.id, job?.status]);

  async function submit() {
    if (!sourceId) return;
    setSubmitting(true);
    setError("");
    try {
      const target = await prepare();
      if (!target || !mounted.current) return;
      const source = await api.getReport(sourceId);
      let latestTarget = await api.getReport(target.id);
      if (!mounted.current) return;
      await api.syncLanguageVariant(source.id, target.id, source.latest_document?.version ?? 1, latestTarget.latest_document?.version ?? 1);
      latestTarget = await api.getReport(target.id);
      if (!mounted.current) return;
      if (source.language_mode !== "EN" && target.language_mode !== "EN") {
        await apply();
        if (mounted.current) setOfflineComplete(true);
        return;
      }
      const next = await api.translateReport(source.id, target.id, source.latest_document?.version ?? 1, latestTarget.latest_document?.version ?? 1, crypto.randomUUID());
      if (mounted.current) setJob(next);
    } catch (caught) { if (mounted.current) setError(failure(caught)); }
    finally { if (mounted.current) setSubmitting(false); }
  }

  if (!sourceId && !job && !error) return null;
  const message = error || (newVersion ? t("translationNewVersion") : pending ? t("translationRunning") : job?.status === "FAILED" ? `${t("translationFailed")} ${job.error?.error_code ?? ""} (${job.request_id})` : job?.status === "SUCCEEDED" ? t(job.preserved_fields.length ? "translationPreserved" : "translationComplete") : offlineComplete ? t("translationComplete") : !report.translation_enabled && !offline ? t("translationDisabled") : "");
  return <section className="status-rail" aria-label={t("syncTranslation")}>
    <span role="status">{message}</span>
    {!isReportReadOnly(report) && sourceId && <button disabled={pending || (!report.translation_enabled && !offline)} onClick={() => void submit()}><Languages size={16} /> {t("syncTranslation")}</button>}
    {newVersion && <button onClick={() => void prepare().then(() => apply()).then((applied) => setNewVersion(!applied)).catch((caught) => setError(failure(caught)))}><RefreshCw size={16} /> {t("reloadTranslation")}</button>}
  </section>;
}