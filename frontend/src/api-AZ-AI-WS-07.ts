export type ReportStatus = "DRAFT" | "REVIEW" | "FINALIZED";

export interface Product {
  id: string;
  product_code: string;
  ticker: string;
  name_en: string;
  name_zh_hant: string | null;
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

export interface NewsProvider {
  key: string;
  title: string;
  description: string;
  /** Whether this environment holds a credential for it. The credential itself never reaches the browser. */
  configured: boolean;
  default: boolean;
}

export interface NewsCandidateInput {
  source_name: string;
  source_url: string;
  published_at: string;
  title: string;
  summary: string;
  ticker: string | null;
}

export type DatasetType = "constituents" | "historical_performance" | "final_analytics";

export interface ImportResult {
  id: string;
  dataset_type: DatasetType;
  diff: { summary: Record<string, number> };
  validation_results: Array<{ check_id: string; status: string; severity: string; fix_hint: string }>;
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
  benchmark_code: string;
  report_date: string;
  status: ReportStatus;
  version: number;
  active_snapshot_id: string | null;
  finalized_document_version: number | null;
  latest_document?: { version: number; checksum: string; content: Record<string, unknown> } | null;
  quality_results?: Array<{ check_id: string; status: string; severity: string; fix_hint: string }>;
  artifacts?: Array<{ id: string; format: string; size_bytes: number }>;
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
  createGoldenSnapshot: (id: string) => request(`/reports/${id}/snapshots`, { method: "POST", body: JSON.stringify({ source_policy: "GOLDEN_FIXTURE" }) }),
  finalize: (id: string, version: number) => request<Report>(`/reports/${id}/finalize`, { method: "POST", body: JSON.stringify({ version }) }),
  saveDocument: (id: string, version: number, content: Record<string, unknown>) => request<{ version: number }>(`/reports/${id}/document`, { method: "PUT", body: JSON.stringify({ version, content }) }),
  render: (id: string) => request<Array<{ id: string; format: string; status: string; artifact_id: string | null }>>(`/reports/${id}/renders`, { method: "POST", body: JSON.stringify({ formats: ["html", "pdf", "docx"] }), headers: { "Idempotency-Key": crypto.randomUUID() } }),
  uploadDataset: (id: string, datasetType: DatasetType, file: File) => { const body = new FormData(); body.append("dataset_type", datasetType); body.append("file", file); return request<ImportResult>(`/reports/${id}/imports`, { method: "POST", body }); },
  uploadConstituents: (id: string, file: File) => { const body = new FormData(); body.append("dataset_type", "constituents"); body.append("file", file); return request<ImportResult>(`/reports/${id}/imports`, { method: "POST", body }); },
  applyImport: (reportId: string, importId: string, reason: string) => request(`/reports/${reportId}/imports/${importId}/apply`, { method: "POST", body: JSON.stringify({ reason }) }),
  calculate: (id: string) => request<{ document_version: number; metrics: Record<string, number | string> }>(`/reports/${id}/calculations`, { method: "POST", body: "{}" }),
  generateDraft: (id: string, version: number, user_prompt: string) => request<{ version: number }>(`/reports/${id}/ai/in-review`, { method: "POST", body: JSON.stringify({ version, user_prompt }) }),
  review: (id: string) => request<{ ready: boolean; blocking: Array<{ check_id: string; fix_hint: string }>; warnings: unknown[] }>(`/reports/${id}/review`),
  listNews: () => request<NewsCandidate[]>("/news"),
  listNewsProviders: () => request<NewsProvider[]>("/news/providers"),
  listReportNewsCandidates: (id: string) => request<NewsCandidate[]>(`/reports/${id}/news/candidates`),
  fetchNewsCandidates: (id: string, scope: "CONSTITUENTS" | "GENERAL", from_date: string, to_date: string, provider?: string) => request<{ provider: string; fetched: number; created: number; items: NewsCandidate[] }>(`/reports/${id}/news/candidates/fetch`, { method: "POST", body: JSON.stringify({ scope, from_date, to_date, page: 0, limit: 100, provider: provider ?? null }) }),
  addNewsCandidate: (id: string, item: NewsCandidateInput) => request<NewsCandidate>(`/reports/${id}/news/candidates`, { method: "POST", body: JSON.stringify(item) }),
  selectNews: (id: string, version: number, selections: NewsSelectionDraft[] | string[]) => {
    const items = selections.map((item, position) => typeof item === "string" ? { news_item_id: item, position } : item);
    return request<{ version: number }>(`/reports/${id}/news`, { method: "PUT", body: JSON.stringify({ version, items }) });
  },
  downloadArtifact: async (id: string) => { const signed = await request<{ download_url: string }>(`/artifacts/${id}/download`); window.location.assign(signed.download_url); },
};
