// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
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
  lane: "PRODUCTION",
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
        constituents: [{
          security_code: "700",
          ticker: "0700.HK",
          name_en: "TENCENT",
          close_price: "500",
          currency: "HKD",
          weight: "1",
          return_1m: "0.01",
          return_3m: "0.03",
          return_6m: "0.06",
          return_ytd: "0.08",
        }],
      },
    },
  },
};

it("uses constituent identity input and refreshes FMP returns for the selected month", async () => {
  vi.spyOn(api, "listDatasets").mockResolvedValue([{
    key: "index_constituents",
    title: "Index constituents",
    description: "Ticker, name, price and weight",
    required: false,
    accepts: [".csv"],
    state: "APPLIED",
    latest_import_id: "identity-1",
    filename: "hstech.csv",
    rows: 30,
    blocking: 0,
    warnings: 0,
  }]);
  const refresh = vi.spyOn(api, "refreshAutomaticData").mockResolvedValue({ changed: true });
  const run = async (work: () => Promise<unknown>) => { await work(); };

  render(<ReportModule report={report} active="constituents" busy={false} run={run} />);

  expect(await screen.findByLabelText("index_constituents data import")).toBeTruthy();
  expect(screen.queryByLabelText("constituent_performance data import")).toBeNull();
  expect(screen.getByLabelText("Automatic FMP constituent returns")).toBeTruthy();
  expect(screen.getByText(/No CSV is required/i)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Load automatically" }));
  await waitFor(() => expect(refresh).toHaveBeenCalledWith(report.id, report.version));
});
