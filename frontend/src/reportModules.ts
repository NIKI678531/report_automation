export const REPORT_MODULES = [
  { id: "review", label: "Review", pageLabel: "01" },
  { id: "performance", label: "Historical Performance", pageLabel: "01" },
  { id: "news", label: "Company News", pageLabel: "02" },
  { id: "constituents", label: "Constituent Performance", pageLabel: "03" },
  { id: "analytics", label: "Final Analytics", pageLabel: "04" },
  { id: "footnotes", label: "Footnotes & Disclosures", pageLabel: "01/03/04" },
] as const;

export type ModuleId = (typeof REPORT_MODULES)[number]["id"];

interface ReportIdentity {
  product_code: string;
  report_date: string;
  latest_document?: { content: Record<string, unknown> } | null;
}

interface ReportContextItem {
  product_code: string;
  report_date: string;
}

export function reportPageLabel(moduleId: ModuleId): string {
  return REPORT_MODULES.find(({ id }) => id === moduleId)?.pageLabel ?? "";
}

export function reportPageEyebrow(moduleId: ModuleId, detail: string): string {
  const pageLabel = reportPageLabel(moduleId);
  const prefix = pageLabel.includes("/") ? "Pages" : "Page";
  return `${prefix} ${pageLabel} · ${detail}`;
}

export function reportMonthName(report: ReportIdentity): string {
  const stored = report.latest_document?.content.month_name;
  if (typeof stored === "string" && stored.trim()) return stored.trim();
  return new Date(`${report.report_date}T00:00:00Z`).toLocaleDateString("en-HK", {
    month: "long",
    timeZone: "UTC",
  });
}

export function reportProductTicker(report: ReportIdentity): string {
  const stored = report.latest_document?.content.product_ticker;
  return typeof stored === "string" && stored.trim() ? stored.trim() : report.product_code;
}

export function reportsForContext<T extends ReportContextItem>(reports: T[], productCode: string, reportDate: string): T[] {
  return reports.filter((report) => report.product_code === productCode && report.report_date === reportDate);
}