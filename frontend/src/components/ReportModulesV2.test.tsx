// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
        historical_performance: { rows: [{ name: "3033.HK", return_1m: "0.1" }] },
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
  it("keeps Historical Performance read-only and automatic", () => {
    render(<ReportModule report={report} active="performance" busy={false} run={run} />);

    expect(screen.getByText(/loaded from the read-only DA-Report snapshot/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Upload file/i })).toBeNull();
  });

  it("shows one merged constituent upload slot", async () => {
    vi.spyOn(api, "listDatasets").mockResolvedValue([{
      key: "constituent_performance",
      title: "Constituent performance",
      description: "One canonical CSV",
      required: true,
      accepts: [".csv"],
      state: "MISSING",
      latest_import_id: null,
      filename: null,
      rows: 0,
      blocking: 0,
      warnings: 0,
    }]);

    render(<ReportModule report={report} active="constituents" busy={false} run={run} />);

    await waitFor(() => expect(screen.getByLabelText("constituent_performance data import")).toBeTruthy());
    expect(screen.getAllByRole("button", { name: /Upload file/i })).toHaveLength(1);
  });

  it("derives Final Analytics without uploads and renders the sector donut", async () => {
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
