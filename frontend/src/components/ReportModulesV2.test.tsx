// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type Report } from "../api";
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

  it("separates the CSV override from automatic CDB and FMP loading", async () => {
    vi.spyOn(api, "listDatasets").mockResolvedValue([
      { key: "index_constituents", title: "Index constituents", description: "Identity override", required: false, accepts: [".csv"], state: "APPLIED", latest_import_id: null, filename: null, rows: 30, blocking: 0, warnings: 0, source_type: "DATA_WAREHOUSE", source_name: "CSOP Data Warehouse" },
      { key: "constituent_returns", title: "Constituent returns", description: "Automatic returns", required: false, accepts: [".csv"], state: "APPLIED", latest_import_id: null, filename: null, rows: 30, blocking: 0, warnings: 0, source_type: "FMP_API", source_name: "Financial Modeling Prep" },
    ]);
    const refresh = vi.spyOn(api, "refreshAutomaticData").mockResolvedValue({ changed: true });

    render(<ReportModule report={report} active="constituents" busy={false} run={run} />);

    expect(await screen.findByText("01 · CSV OVERRIDE")).toBeTruthy();
    const csvOverride = screen.getByLabelText("index_constituents data import");
    expect(within(csvOverride).getByRole("button", { name: /Upload file/i })).toBeTruthy();
    const input = csvOverride.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input.multiple).toBe(false);
    expect(input.accept).toContain(".csv");
    expect(within(csvOverride).getByText(/CSOP Data Warehouse · 30 rows/i)).toBeTruthy();
    expect(within(csvOverride).queryByRole("button", { name: /Delete data/i })).toBeNull();

    const automatic = screen.getByLabelText("Automatic FMP constituent returns");
    expect(within(automatic).getByText("CDB constituents + FMP returns")).toBeTruthy();
    expect(within(automatic).getByText(/No CSV is required/i)).toBeTruthy();
    expect(within(automatic).getByText(/30 FMP return rows · 30 constituent identities/i)).toBeTruthy();
    fireEvent.click(within(automatic).getByRole("button", { name: "Load automatically" }));
    await waitFor(() => expect(refresh).toHaveBeenCalledWith(report.id, report.version));

    expect(screen.getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "Code", "Constituent", "Price", "Weight", "1M", "3M", "6M", "YTD",
    ]);
    expect(screen.getByRole("rowheader").textContent).toBe("0001.HK");
  });
  it("renders Final Analytics from the bound Page 04 results and sector donut", async () => {
    vi.spyOn(api, "listDatasets").mockResolvedValue([]);

    render(<ReportModule report={report} active="analytics" busy={false} run={run} />);

    expect(screen.queryByRole("button", { name: /Upload file/i })).toBeNull();
    expect(screen.getByRole("img", { name: /Index Sectors Breakdown/i })).toBeTruthy();
    expect(screen.getByText(/Derived by the backend from the active constituent snapshot/i)).toBeTruthy();
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
