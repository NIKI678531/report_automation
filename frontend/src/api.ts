export type ReportStatus = "DRAFT" | "DATA_READY" | "EDITING" | "QA_BLOCKED" | "READY_TO_FINALIZE" | "REVIEW" | "FINALIZED" | "ARCHIVED";
export type OutputFormat = "pdf" | "html" | "docx";

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

export interface CompanyNewsCatalogItem {
  provider: "DA_REPORT";
  external_id: string;
  source_url: string;
  source_code: string;
  source_name: string;
  source_name_zh: string | null;
  published_at: string;
  published_at_source: "published_at" | "fetched_at";
  fetched_at: string;
  title: string;
  title_en: string | null;
  title_zh: string | null;
  summary: string;
  summary_en: string | null;
  summary_zh: string | null;
  category: "Corporate";
  region: string | null;
  sentiment: string | null;
  importance_score: number | null;
  model: string | null;
}

export interface CompanyNewsCatalogPage {
  items: CompanyNewsCatalogItem[];
  total: number;
  has_more: boolean;
  next_cursor: string | null;
  facets: {
    sources: Array<{ value: string; label: string; label_zh: string | null; count: number }>;
    sentiments: Record<string, number>;
    importance: Record<string, number>;
    date_min: string | null;
    date_max: string | null;
  };
}

export interface CompanyNewsCatalogQuery {
  query?: string;
  source?: string;
  sentiment?: string;
  importance?: "LOW" | "MEDIUM" | "HIGH";
  from_date?: string;
  to_date?: string;
  sort?: "newest" | "oldest";
  cursor?: string;
  limit?: number;
}

export type DatasetType = "constituent_performance" | "index_constituents" | "constituent_returns" | "total_return_series" | "fund_kpi_daily" | "trading_calendar" | "index_events";
export type ClearableDatasetType = Extract<DatasetType, "constituent_performance" | "index_constituents" | "constituent_returns">;

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

export interface ImportBatchFile {
  id: string;
  filename: string;
  detected_type: string;
  mapping_version: number | null;
  status: "VALIDATED" | "REJECTED" | "NEEDS_MAPPING" | "UNSUPPORTED" | "EXCLUDED" | "APPLIED";
  row_count: number;
  errors: Array<{ error_code?: string; check_id?: string; severity: string; message?: string; fix_hint?: string }>;
  preview: { columns: string[]; rows: Array<Record<string, unknown>> };
}

export interface ImportBatch {
  id: string;
  report_id: string;
  status: "STAGING" | "INCOMPLETE" | "BLOCKED" | "PARTIAL_READY" | "READY" | "APPLIED" | "DISCARDED";
  coverage: {
    mode?: "CANONICAL" | "SPLIT";
    identity?: { state: "READY" | "MISSING"; source?: "BATCH" | "ACTIVE_SNAPSHOT" | null; import_ids: string[] };
    returns?: { state: "READY" | "MISSING"; source?: "BATCH" | null; import_ids: string[] };
    unsupported_count?: number;
  };
  errors: Array<{ error_code?: string; severity: string; message?: string; fix_hint?: string }>;
  reason: string | null;
  applied_snapshot_id: string | null;
  requires_reason?: boolean;
  files: ImportBatchFile[];
  merge_preview: {
    report_month: string | null;
    as_of_date: string | null;
    sources: Array<{ dataset_type: string; filename: string }>;
    rows: Array<{
      security_code: string;
      name_en: string | null;
      name_zh_hant: string | null;
      close_price: string | number | null;
      currency: string | null;
      weight: string | number | null;
      return_1m: string | number | null;
      return_3m: string | number | null;
      return_6m: string | number | null;
      return_ytd: string | number | null;
    }>;
    unmatched_identity_codes: string[];
    unmatched_return_codes: string[];
  };
}

export interface NewsSelectionDraft {
  news_item_id?: string;
  provider?: "DA_REPORT";
  external_id?: string;
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
  /** Whether this report's data may be distributed. TESTING artifacts are watermarked. */
  lane: "PRODUCTION" | "TESTING";
  revision: number;
  version: number;
  active_snapshot_id: string | null;
  finalized_document_version: number | null;
  created_at?: string;
  updated_at?: string;
  latest_document?: { version: number; checksum: string; content: Record<string, unknown> } | null;
  quality_results?: Array<{ check_id: string; status: string; severity: string; fix_hint: string }>;
  artifacts?: Array<{ id: string; format: OutputFormat; size_bytes: number; checksum: string }>;
}

export interface RenderJob {
  id: string;
  format: OutputFormat;
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
  render: (id: string, formats: OutputFormat[]) => request<RenderJob[]>(`/reports/${id}/renders`, { method: "POST", body: JSON.stringify({ formats }), headers: { "Idempotency-Key": crypto.randomUUID() } }),
  getJob: (id: string) => request<RenderJob>(`/jobs/${id}`),
  listDatasets: (id: string) => request<DatasetSlot[]>(`/reports/${id}/datasets`),
  uploadDataset: (id: string, datasetType: DatasetType, file: File) => { const body = new FormData(); body.append("dataset_type", datasetType); body.append("file", file); return request<ImportResult>(`/reports/${id}/imports`, { method: "POST", body }); },
  uploadImportBatch: (id: string, files: File[]) => { const body = new FormData(); files.forEach((file) => body.append("files", file)); return request<ImportBatch>(`/reports/${id}/import-batches`, { method: "POST", body }); },
  getImportBatch: (reportId: string, batchId: string) => request<ImportBatch>(`/reports/${reportId}/import-batches/${batchId}`),
  excludeImportBatchFile: (reportId: string, batchId: string, importId: string) => request<ImportBatch>(`/reports/${reportId}/import-batches/${batchId}/files/${importId}/exclude`, { method: "POST", body: JSON.stringify({}) }),
  applyImportBatch: (reportId: string, batchId: string, version: number, reason?: string) => request(`/reports/${reportId}/import-batches/${batchId}/apply`, { method: "POST", body: JSON.stringify({ version, ...(reason ? { reason } : {}) }) }),
  discardImportBatch: (reportId: string, batchId: string) => request<ImportBatch>(`/reports/${reportId}/import-batches/${batchId}/discard`, { method: "POST", body: JSON.stringify({}) }),
  refreshAutomaticData: (reportId: string, version: number) => request<{ changed: boolean }>(`/reports/${reportId}/automatic-data/refresh`, { method: "POST", body: JSON.stringify({ version }) }),
  applyImport: (reportId: string, importId: string, reason?: string) => request(`/reports/${reportId}/imports/${importId}/apply`, { method: "POST", body: JSON.stringify(reason ? { reason } : {}) }),
  discardImport: (reportId: string, importId: string) => request(`/reports/${reportId}/imports/${importId}/discard`, { method: "POST", body: JSON.stringify({}) }),
  clearDataset: (reportId: string, datasetType: ClearableDatasetType, version: number) => request(`/reports/${reportId}/datasets/${datasetType}/clear`, { method: "POST", body: JSON.stringify({ version }) }),
  generateDraft: (id: string, version: number, user_prompt: string) => request<{ version: number }>(`/reports/${id}/ai/in-review`, { method: "POST", body: JSON.stringify({ version, user_prompt }) }),
  review: (id: string) => request<{ ready: boolean; blocking: Array<{ check_id: string; fix_hint: string }>; warnings: Array<{ check_id?: string; fix_hint?: string }> }>(`/reports/${id}/review`),
  listNewsProviders: () => request<NewsProvider[]>("/news/providers"),
  listCompanyNewsCatalog: (id: string, filters: CompanyNewsCatalogQuery = {}) => {
    const parameters = new URLSearchParams();
    if (filters.query) parameters.set("query", filters.query);
    if (filters.source) parameters.set("source", filters.source);
    if (filters.sentiment) parameters.set("sentiment", filters.sentiment);
    if (filters.importance) parameters.set("importance", filters.importance);
    if (filters.from_date) parameters.set("from_date", filters.from_date);
    if (filters.to_date) parameters.set("to_date", filters.to_date);
    if (filters.sort) parameters.set("sort", filters.sort);
    if (filters.cursor) parameters.set("cursor", filters.cursor);
    if (filters.limit) parameters.set("limit", String(filters.limit));
    const query = parameters.toString();
    return request<CompanyNewsCatalogPage>(`/reports/${id}/news/catalog${query ? `?${query}` : ""}`);
  },
  listReportNewsCandidates: (id: string) => request<NewsCandidate[]>(`/reports/${id}/news/candidates`),
  fetchNewsCandidates: (id: string, scope: "CONSTITUENTS" | "GENERAL", from_date: string, to_date: string, provider?: string, ensure = false) => request<{ provider: string; fetched: number; created: number; items: NewsCandidate[] }>(`/reports/${id}/news/candidates/fetch`, { method: "POST", body: JSON.stringify({ scope, from_date, to_date, page: 0, limit: 100, provider, ensure }) }),
  addNewsCandidate: (id: string, item: NewsCandidateInput) => request<NewsCandidate>(`/reports/${id}/news/candidates`, { method: "POST", body: JSON.stringify(item) }),
  selectNews: (id: string, version: number, selections: NewsSelectionDraft[] | string[]) => {
    const items = selections.map((item, position) => typeof item === "string" ? { news_item_id: item, position } : item);
    return request<{ version: number }>(`/reports/${id}/news`, { method: "PUT", body: JSON.stringify({ version, items }) });
  },
  downloadArtifact: async (id: string) => { const signed = await request<{ download_url: string }>(`/artifacts/${id}/download`); window.location.assign(signed.download_url); },
};
