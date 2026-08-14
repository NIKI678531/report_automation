// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type ImportBatch, type Report } from "../api";
import { ReportModule } from "./ReportModulesV2";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const report: Report = {
  id: "report-1",
  product_code: "3033",
  product_name: "CSOP Hang Seng TECH Index ETF",
  constituent_index_code: "HSTECH",
  benchmark_instrument_code: "HSTECHN",
  benchmark_code: "HSTECH",
  report_date: "2026-06-30",
  status: "EDITING",
  lane: "PRODUCTION",
  revision: 1,
  version: 4,
  active_snapshot_id: "snapshot-1",
  finalized_document_version: null,
  latest_document: {
    version: 4,
    checksum: "document-checksum",
    content: {
      sections: {
        historical_performance: {
          rows: [
            { role: "FUND", name: "Warehouse fund label", return_1m: "0.1", return_3m: "0.2", return_6m: "0.3", return_ytd: "0.4" },
            { role: "BENCHMARK", name: "Warehouse benchmark label", return_1m: "0.11", return_3m: "0.21", return_6m: "0.31", return_ytd: "0.41" },
          ],
          requested_report_month: "2026-06",
          effective_as_of: "2026-06-30",
          source_name: "CSOP Data Warehouse",
          source_mapping: { tradar_code: "CO-CHST", class_id: "CLS00178", benchmark_index_ticker: "HSTECHN Index" },
          monthly_observations: [{
            month: "2026-06",
            month_label: "June 2026",
            effective_as_of: "2026-06-30",
            rows: [
              { role: "FUND", name: "3033.HK", return_1m: "0.1", return_3m: "0.2", return_6m: "0.3", return_ytd: "0.4" },
              { role: "BENCHMARK", name: "HSTECHN Index", return_1m: "0.11", return_3m: "0.21", return_6m: "0.31", return_ytd: "0.41" },
            ],
          }],
        },
        constituents: [{ security_code: "1", ticker: "0001.HK", name_en: "Alpha", weight: "1", return_1m: "0.1" }],
        analytics: {
          top10: [{ issuer: "Alpha", weight: "1" }],
          sectors: [{ code: "70", sector: "Information Technology", weight: "1" }],
          sector_chart: {
            chart_code: "industry_breakdown",
            alt_text: "Index sector breakdown: Information Technology 100.0%",
            series: [{
              code: "70",
              label: "Information Technology",
              raw_value: "1",
              unit: "RATIO",
              display_value: "100.0%",
              sort_order: 1,
              color_token: "industry.hsics.70",
              start_angle: "0",
              end_angle: "360",
            }],
          },
          top: [{ issuer: "Alpha", return: "0.1" }],
          bottom: [{ issuer: "Alpha", return: "0.1" }],
          portfolio: [{ label: "Number of holdings", value: "1" }],
        },
        footnotes: {
          historical: "Historical disclosure from this report.",
          constituents: "Constituent disclosure from this report.",
          analytics: "Analytics disclosure from this report.",
        },
      },
    },
  },
};

const run = async (work: () => Promise<unknown>) => { await work(); };

describe("report module data responsibilities", () => {
  it("matches the approved five-column Historical Performance table", async () => {
    const refresh = vi.spyOn(api, "refreshAutomaticData").mockResolvedValue({ changed: false });
    render(<ReportModule report={report} active="performance" busy={false} run={run} />);

    expect(screen.getByRole("button", { name: /Refresh data warehouse/i })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Historical Performance of 3033.HK and Hang Seng TECH Index*" })).toBeTruthy();
    expect(screen.getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "", "1-month return (%)", "3-month return (%)", "6-month return (%)", "YTD return (%)",
    ]);
    expect(screen.getAllByRole("rowheader").map((cell) => cell.textContent)).toEqual(["3033.HK", "HSTECHN Index"]);
    expect(screen.getByText("10.00")).toBeTruthy();
    expect(screen.getByText("41.00")).toBeTruthy();
    expect(screen.queryByRole("combobox", { name: /Months to display/i })).toBeNull();
    expect(screen.queryByText("June 2026")).toBeNull();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("shows one unrestricted multi-file constituent drop zone", async () => {
    render(<ReportModule report={report} active="constituents" busy={false} run={run} />);

    expect(screen.getByLabelText("Constituent multi-file import")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Choose files/i })).toBeTruthy();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input.multiple).toBe(true);
    expect(input.getAttribute("accept")).toBeNull();
    expect(screen.getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "Stock Code", "Stock Name", "Closing Price (HKD)", "Weighting (%)", "1-month return (%)", "3-month return (%)", "6-month return (%)", "YTD return (%)",
    ]);
    expect(screen.getByRole("rowheader").textContent).toBe("1");
    expect(screen.queryByText("0001.HK")).toBeNull();
    expect(screen.getByText("100.00")).toBeTruthy();
    expect(screen.getByText("10.00")).toBeTruthy();
    expect(screen.getAllByText("N/A").length).toBeGreaterThanOrEqual(4);
  });

  it("deletes current split Page 04 data in dependency order after confirmation", async () => {
    vi.spyOn(api, "listDatasets").mockResolvedValue([
      { key: "index_constituents", title: "Identity", description: "", required: true, accepts: [".csv"], state: "APPLIED", latest_import_id: "identity-1", filename: "identity.csv", rows: 30, blocking: 0, warnings: 0 },
      { key: "constituent_returns", title: "Returns", description: "", required: true, accepts: [".xlsx"], state: "APPLIED", latest_import_id: "returns-1", filename: "returns.xlsx", rows: 30, blocking: 0, warnings: 0 },
    ]);
    const clearDataset = vi.spyOn(api, "clearDataset").mockResolvedValue({} as never);
    vi.spyOn(api, "getReport").mockResolvedValue({ ...report, version: 5 });
    render(<ReportModule report={report} active="constituents" busy={false} run={run} />);

    fireEvent.click(screen.getByRole("button", { name: "Delete current Page 04 data" }));
    expect(screen.getByText(/Historical snapshots and audit records will remain available/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Yes, delete current data" }));

    await waitFor(() => expect(clearDataset).toHaveBeenCalledTimes(2));
    expect(clearDataset.mock.calls).toEqual([
      [report.id, "constituent_returns", 4],
      [report.id, "index_constituents", 5],
    ]);
  });

  it("shows the complete merged Page 04 preview before apply", async () => {
    const staged: ImportBatch = {
      id: "batch-1",
      report_id: report.id,
      status: "READY",
      coverage: {
        mode: "SPLIT",
        identity: { state: "READY", import_ids: ["identity-1"] },
        returns: { state: "READY", import_ids: ["returns-1"] },
      },
      errors: [],
      reason: null,
      applied_snapshot_id: null,
      files: [
        { id: "identity-1", filename: "identity.csv", detected_type: "index_constituents", mapping_version: 1, status: "VALIDATED", row_count: 1, errors: [], preview: { columns: [], rows: [] } },
        { id: "returns-1", filename: "returns.xlsx", detected_type: "constituent_returns", mapping_version: 1, status: "VALIDATED", row_count: 1, errors: [], preview: { columns: [], rows: [] } },
      ],
      merge_preview: {
        report_month: "2026-06",
        as_of_date: "2026-06-30",
        sources: [
          { dataset_type: "index_constituents", filename: "identity.csv" },
          { dataset_type: "constituent_returns", filename: "returns.xlsx" },
        ],
        rows: [{
          security_code: "700", name_en: "TENCENT", name_zh_hant: "騰訊控股", close_price: "429.8", currency: "HKD", weight: "0.08302929908",
          return_1m: "0.006086142", return_3m: null, return_6m: "-0.2741384", return_ytd: "-0.2741384",
        }],
        unmatched_identity_codes: [],
        unmatched_return_codes: [],
      },
    };
    vi.spyOn(api, "uploadImportBatch").mockResolvedValue(staged);
    render(<ReportModule report={report} active="constituents" busy={false} run={run} />);

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["identity"], "identity.csv", { type: "text/csv" })] } });

    const preview = await screen.findByLabelText("Merged constituent preview");
    expect(within(preview).getByText("Report month 2026-06 · As of 2026-06-30")).toBeTruthy();
    expect(within(preview).getByText("700")).toBeTruthy();
    expect(within(preview).getByText("TENCENT")).toBeTruthy();
    expect(within(preview).getByText("429.80")).toBeTruthy();
    expect(within(preview).getByText("8.30")).toBeTruthy();
    expect(within(preview).getByText("0.61")).toBeTruthy();
    expect(within(preview).getByText("N/A")).toBeTruthy();
  });

  it("saves identity-only Page 04 data while returns are still missing", async () => {
    const identityOnlyReport = structuredClone(report);
    const sections = identityOnlyReport.latest_document?.content.sections as Record<string, unknown>;
    sections.constituents = [];
    const staged: ImportBatch = {
      id: "identity-batch",
      report_id: report.id,
      status: "PARTIAL_READY",
      coverage: {
        mode: "SPLIT",
        identity: { state: "READY", source: "BATCH", import_ids: ["identity-1"] },
        returns: { state: "MISSING", source: null, import_ids: [] },
      },
      errors: [],
      reason: null,
      applied_snapshot_id: null,
      requires_reason: false,
      files: [
        { id: "identity-1", filename: "identity.csv", detected_type: "index_constituents", mapping_version: 1, status: "VALIDATED", row_count: 1, errors: [], preview: { columns: [], rows: [] } },
      ],
      merge_preview: {
        report_month: "2026-06",
        as_of_date: "2026-06-30",
        sources: [{ dataset_type: "index_constituents", filename: "identity.csv" }],
        rows: [{ security_code: "700", name_en: "TENCENT", name_zh_hant: null, close_price: "429.8", currency: "HKD", weight: "1", return_1m: null, return_3m: null, return_6m: null, return_ytd: null }],
        unmatched_identity_codes: ["700"],
        unmatched_return_codes: [],
      },
    };
    vi.spyOn(api, "uploadImportBatch").mockResolvedValue(staged);
    const applyBatch = vi.spyOn(api, "applyImportBatch").mockResolvedValue({});
    render(<ReportModule report={identityOnlyReport} active="constituents" busy={false} run={run} />);

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["identity"], "identity.csv", { type: "text/csv" })] } });

    expect(await screen.findByText("Identity data ready to save")).toBeTruthy();
    expect(screen.getByText(/returns will display as N\/A until added later/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save available data" }));
    await waitFor(() => expect(applyBatch).toHaveBeenCalledWith(report.id, "identity-batch", report.version, undefined));
  });

  it("renders Final Analytics from the bound Page 04 results and sector donut", async () => {
    vi.spyOn(api, "listDatasets").mockResolvedValue([]);

    render(<ReportModule report={report} active="analytics" busy={false} run={run} />);

    expect(screen.queryByRole("button", { name: /Upload file/i })).toBeNull();
    expect(screen.getByRole("img", { name: /Index Sectors Breakdown/i })).toBeTruthy();
    expect(screen.getByText(/Derived only from the validated Page 04 upload/i)).toBeTruthy();
  });

  it("edits the three report-backed disclosures and identifies their bound modules", async () => {
    const saveDocument = vi.spyOn(api, "saveDocument").mockResolvedValue({ version: 5 });

    render(<ReportModule report={report} active="footnotes" busy={false} run={run} />);

    expect(screen.getByText("Page 06 · Free layout")).toBeTruthy();
    expect(screen.getAllByRole("textbox")).toHaveLength(3);
    expect(screen.getByDisplayValue("Historical disclosure from this report.")).toBeTruthy();
    expect(screen.getByText(/Bound to Historical Performance/)).toBeTruthy();
    expect(screen.getByText(/Bound to Constituent Performance/)).toBeTruthy();
    expect(screen.getByText(/Bound to Final Analytics/)).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Historical footnote"), { target: { value: "Edited report-specific disclosure." } });
    fireEvent.click(screen.getByRole("button", { name: "Save disclosures" }));

    await waitFor(() => expect(saveDocument).toHaveBeenCalledOnce());
    const [reportId, version, content] = saveDocument.mock.calls[0];
    expect(reportId).toBe("report-1");
    expect(version).toBe(4);
    expect(((content.sections as Record<string, unknown>).footnotes as Record<string, string>)).toEqual({
      historical: "Edited report-specific disclosure.",
      constituents: "Constituent disclosure from this report.",
      analytics: "Analytics disclosure from this report.",
    });
  });

  it("leaves missing disclosures empty for another product instead of inventing content", () => {
    const anotherProduct = structuredClone(report);
    anotherProduct.product_code = "3037";
    const sections = anotherProduct.latest_document?.content.sections as Record<string, unknown>;
    sections.footnotes = { historical: "3037 report source text." };

    render(<ReportModule report={anotherProduct} active="footnotes" busy={false} run={run} />);

    expect((screen.getByLabelText("Historical footnote") as HTMLTextAreaElement).value).toBe("3037 report source text.");
    expect((screen.getByLabelText("Constituents footnote") as HTMLTextAreaElement).value).toBe("");
    expect((screen.getByLabelText("Analytics footnote") as HTMLTextAreaElement).value).toBe("");
  });
});
