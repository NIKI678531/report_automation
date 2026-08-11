// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
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
            slices: [{ code: "70", label: "Information Technology", weight: "1", start_angle: "0", end_angle: "360", color_index: 2 }],
          },
          top: [{ issuer: "Alpha", return: "0.1" }],
          bottom: [{ issuer: "Alpha", return: "0.1" }],
          portfolio: [{ label: "Number of holdings", value: "1" }],
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
});