export const REPORT_MODULES = [
	{ id: "review", label: "Review", pageLabel: "01" },
	{ id: "performance", label: "Historical Performance", pageLabel: "02" },
	{ id: "news", label: "Company News", pageLabel: "03" },
	{ id: "constituents", label: "Constituent Performance", pageLabel: "04" },
	{ id: "analytics", label: "Final Analytics", pageLabel: "05" },
	{ id: "footnotes", label: "Footnotes & Disclosures", pageLabel: "06" },
] as const;

export const FOOTNOTE_SECTIONS = [
	{ key: "historical", label: "Historical", boundTo: "Historical Performance" },
	{ key: "constituents", label: "Constituents", boundTo: "Constituent Performance" },
	{ key: "analytics", label: "Analytics", boundTo: "Final Analytics" },
] as const;

export type FootnoteSectionKey = (typeof FOOTNOTE_SECTIONS)[number]["key"];

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

interface ConstituentIndexIdentity {
	constituent_index_code: string;
}

export function reportPageLabel(moduleId: ModuleId): string {
	return REPORT_MODULES.find(({ id }) => id === moduleId)?.pageLabel ?? "";
}

export function reportPageEyebrow(moduleId: ModuleId, detail: string): string {
	const pageLabel = reportPageLabel(moduleId);
	return `Page ${pageLabel} · ${detail}`;
}

export function reportConstituentsTitle(report: ConstituentIndexIdentity): string {
	return `The Performance of ${report.constituent_index_code} Constituents`;
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
