export type ReportStatus = "DRAFT" | "DATA_READY" | "EDITING" | "QA_BLOCKED" | "READY_TO_FINALIZE" | "REVIEW" | "FINALIZED" | "ARCHIVED";

export interface Product {
  id: string;
  product_code: string;
  ticker: string;
  name_en: string;
  name_zh_hant: string | null;
  constituent_index_code: string;
  constituent_index_name: string | null;
  benchmark_instrument_code: string;
  benchmark_instrument_name: string | null;
  benchmark_code: string;
  benchmark_name: string | null;
  currency: string;
  timezone: string;
  valid_from: string;
  valid_to: string | null;
  is_active: boolean;
  display_order: number;
  template_version: string;
  design_token_version: string;
  expected_constituent_count: number | null;
  formula_profile: string;
  source: string;
}

export interface NewsCandidate {
  id: string;
  source_name: string;
  source_url: string;
  published_at: string;
  title: string;
  summary: string;
  security_code: string | null;
  ticker: string | null;
  importance: "LOW" | "MEDIUM" | "HIGH";
  match_confidence: number;
  site: string | null;
  provider: string | null;
}

export interface NewsCandidateInput {
  source_name: string;
  source_url: string;
  published_at: string;
  title: string;
  summary: string;
  ticker: string | null;
}

export interface NewsProvider {
  key: string;
  title: string;
  description: string;
  configured: boolean;
  default: boolean;
}

export type DatasetType = "index_constituents" | "constituent_returns" | "total_return_series" | "fund_kpi_daily" | "trading_calendar" | "index_events";

export interface DatasetSlot {
  key: DatasetType | "industry_master";
  title: string;
  description: string;
  required: boolean;
  accepts: string[];
  state: "MISSING" | "AVAILABLE" | "VALIDATED" | "NEEDS_MAPPING" | "REJECTED" | "APPLIED";
  latest_import_id: string | null;
  filename: string | null;
  rows: number;
  blocking: number;
  warnings: number;
}

export interface ImportResult {
  id: string;
  dataset_type: DatasetType;
  status: "VALIDATED" | "NEEDS_MAPPING" | "REJECTED" | "APPLIED";
  diff: { summary: Record<string, number> };
  validation_results: Array<{ check_id?: string; error_code?: string; status?: string; severity: string; message?: string; fix_hint: string; field?: string | null; entity_id?: string | null }>;
  preview: { columns: string[]; rows: Array<Record<string, unknown>>; total: number };
  summary: { rows_parsed: number; blocking: number; warnings: number };
  apply_mode: "FIRST_APPLY" | "OVERWRITE";
  requires_reason: boolean;
}

export interface NewsSelectionDraft {
  news_item_id: string;
  position: number;
  title_override?: string;
  summary_override?: string;
}

export interface Report {
  id: string;
  product_code: string;
  product_name: string;
  constituent_index_code: string;
  benchmark_instrument_code: string;
  benchmark_code: string;
  report_date: string;
  status: ReportStatus;
  revision: number;
  version: number;
  active_snapshot_id: string | null;
  finalized_document_version: number | null;
  latest_document?: { version: number; checksum: string; content: Record<string, unknown> } | null;
  quality_results?: Array<{ check_id: string; status: string; severity: string; fix_hint: string }>;
  artifacts?: Array<{ id: string; format: string; size_bytes: number; checksum: string }>;
}

export interface RenderJob {
  id: string;
  format: string;
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELED";
  progress: number;
  stage: string;
  error: { error_code?: string; message?: string } | null;
  artifact_id: string | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isForm = init?.body instanceof FormData;
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers: { ...(!isForm ? { "Content-Type": "application/json" } : {}), "X-Request-ID": crypto.randomUUID(), ...init?.headers },
  });
  if (!response.ok) throw new Error((await response.text()) || `Request failed: ${response.status}`);
  return response.json() as Promise<T>;
}

export const api = {
  listProducts: (asOfDate: string) => request<Product[]>(`/products?as_of_date=${encodeURIComponent(asOfDate)}`),
  listReports: () => request<Report[]>("/reports"),
  getReport: (id: string) => request<Report>(`/reports/${id}`),
  createReport: (report_date: string, product_code = "3033") => request<Report>("/reports", { method: "POST", body: JSON.stringify({ product_code, report_date }) }),
  finalize: (id: string, version: number) => request<Report>(`/reports/${id}/finalize`, { method: "POST", body: JSON.stringify({ version }) }),
  saveDocument: (id: string, version: number, content: Record<string, unknown>) => request<{ version: number }>(`/reports/${id}/document`, { method: "PATCH", body: JSON.stringify({ version, content }) }),
  render: (id: string) => request<RenderJob[]>(`/reports/${id}/renders`, { method: "POST", body: JSON.stringify({ formats: ["html", "pdf", "docx"] }), headers: { "Idempotency-Key": crypto.randomUUID() } }),
  listDatasets: (id: string) => request<DatasetSlot[]>(`/reports/${id}/datasets`),
  uploadDataset: (id: string, datasetType: DatasetType, file: File) => { const body = new FormData(); body.append("dataset_type", datasetType); body.append("file", file); return request<ImportResult>(`/reports/${id}/imports`, { method: "POST", body }); },
  applyImport: (reportId: string, importId: string, reason?: string) => request(`/reports/${reportId}/imports/${importId}/apply`, { method: "POST", body: JSON.stringify(reason ? { reason } : {}) }),
  generateDraft: (id: string, version: number, user_prompt: string) => request<{ version: number }>(`/reports/${id}/ai/in-review`, { method: "POST", body: JSON.stringify({ version, user_prompt }) }),
  review: (id: string) => request<{ ready: boolean; blocking: Array<{ check_id: string; fix_hint: string }>; warnings: unknown[] }>(`/reports/${id}/review`),
  listNewsProviders: () => request<NewsProvider[]>("/news/providers"),
  listReportNewsCandidates: (id: string) => request<NewsCandidate[]>(`/reports/${id}/news/candidates`),
  fetchNewsCandidates: (id: string, scope: "CONSTITUENTS" | "GENERAL", from_date: string, to_date: string, provider?: string, ensure = false) => request<{ provider: string; fetched: number; created: number; items: NewsCandidate[] }>(`/reports/${id}/news/candidates/fetch`, { method: "POST", body: JSON.stringify({ scope, from_date, to_date, page: 0, limit: 100, provider, ensure }) }),
  addNewsCandidate: (id: string, item: NewsCandidateInput) => request<NewsCandidate>(`/reports/${id}/news/candidates`, { method: "POST", body: JSON.stringify(item) }),
  selectNews: (id: string, version: number, selections: NewsSelectionDraft[] | string[]) => {
    const items = selections.map((item, position) => typeof item === "string" ? { news_item_id: item, position } : item);
    return request<{ version: number }>(`/reports/${id}/news`, { method: "PUT", body: JSON.stringify({ version, items }) });
  },
  downloadArtifact: async (id: string) => { const signed = await request<{ download_url: string }>(`/artifacts/${id}/download`); window.location.assign(signed.download_url); },
};
