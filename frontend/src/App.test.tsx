// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { api, type Product, type Report } from "./api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const product3033: Product = {
  id: "product-3033",
  product_code: "3033",
  ticker: "3033.HK",
  name_en: "CSOP Hang Seng TECH Index ETF",
  name_zh_hant: null,
  constituent_index_code: "HSTECH",
  constituent_index_name: "Hang Seng TECH Index",
  benchmark_instrument_code: "HSTECHN",
  benchmark_instrument_name: "HSTECHN Index",
  benchmark_code: "HSTECH",
  benchmark_name: "Hang Seng TECH Index",
  currency: "HKD",
  timezone: "Asia/Hong_Kong",
  valid_from: "2020-08-28",
  valid_to: null,
  is_active: true,
  display_order: 10,
  template_version: "3033-v2",
  design_token_version: "3033-v2",
  expected_constituent_count: 30,
  formula_profile: "hstech-2026.1",
  source: "PROJECT_BASELINE",
};

function report(id: string, reportDate: string, status: Report["status"] = "DRAFT", revision = 1): Report {
  const monthName = new Date(`${reportDate}T00:00:00Z`).toLocaleDateString("en-HK", { month: "long", timeZone: "UTC" });
  return {
    id,
    product_code: "3033",
    product_name: "CSOP Hang Seng TECH Index ETF (3033.HK)",
    constituent_index_code: "HSTECH",
    benchmark_instrument_code: "HSTECHN",
    benchmark_code: "HSTECH",
    report_date: reportDate,
    status,
    lane: "PRODUCTION",
    revision,
    version: revision,
    active_snapshot_id: null,
    finalized_document_version: status === "FINALIZED" ? 1 : null,
    created_at: `${reportDate}T00:00:00Z`,
    latest_document: {
      version: 1,
      checksum: id,
      content: {
        month_name: monthName,
        product_ticker: "3033.HK",
        sections: {
          month_in_review: { title: `${monthName} in Review`, display_title: `${monthName} in Review`, summary: "", drivers: [], monitor: [], outlook: "" },
          historical_performance: { rows: [] },
          company_news: [],
          constituents: [],
          analytics: { top10: [], top: [], bottom: [], portfolio: [] },
          footnotes: { historical: "", constituents: "", analytics: "" },
        },
      },
    },
    quality_results: [],
    artifacts: [],
  };
}

describe("3033 product scope", () => {
  it("renders a fixed 3033 header instead of a fund dropdown", async () => {
    vi.spyOn(api, "listProducts").mockResolvedValue([product3033]);
    vi.spyOn(api, "listReports").mockResolvedValue([]);

    render(<App />);

    await waitFor(() => expect(screen.getByLabelText("Fund 3033")).toBeTruthy());
    expect(screen.getByText("CSOP Hang Seng TECH Index ETF")).toBeTruthy();
    expect(screen.queryByRole("combobox", { name: "Fund" })).toBeNull();
    expect(screen.getByLabelText("Report month").getAttribute("type")).toBe("month");
    expect(screen.getByLabelText("Report month").getAttribute("min")).toBeNull();
    expect(screen.getByLabelText("Report month").getAttribute("max")).toBeNull();
  });

  it("switches directly to the newest production draft for any selected month", async () => {
    const july = report("july", "2026-07-31", "EDITING", 1);
    const december = report("december-r2", "2025-12-31", "DRAFT", 2);
    vi.spyOn(api, "listProducts").mockResolvedValue([product3033]);
    vi.spyOn(api, "listReports").mockResolvedValue([july, december]);
    vi.spyOn(api, "getReport").mockImplementation(async (id) => id === december.id ? december : july);

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText("Report month")).toHaveProperty("value", "2026-07"));

    fireEvent.change(screen.getByLabelText("Report month"), { target: { value: "2025-12" } });

    await waitFor(() => expect(screen.getByLabelText("Report version")).toHaveProperty("value", december.id));
    expect(screen.getByRole("option", { name: "2025-12-31 · r2 · DRAFT" })).toBeTruthy();
  });

  it("auto-saves editable disclosures before changing report month", async () => {
    const july = report("july", "2026-07-31", "EDITING");
    const june = report("june", "2026-06-30", "DRAFT");
    vi.spyOn(api, "listProducts").mockResolvedValue([product3033]);
    vi.spyOn(api, "listReports").mockResolvedValue([july, june]);
    vi.spyOn(api, "getReport").mockImplementation(async (id) => id === june.id ? june : july);
    const saveDocument = vi.spyOn(api, "saveDocument").mockResolvedValue({ version: 2 });

    render(<App />);
    await waitFor(() => expect(screen.getByRole("button", { name: /Footnotes & Disclosures/ })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Footnotes & Disclosures/ }));
    const footnote = await screen.findByLabelText("Historical footnote");
    fireEvent.change(footnote, { target: { value: "Reviewed disclosure" } });
    fireEvent.change(screen.getByLabelText("Report month"), { target: { value: "2026-06" } });

    await waitFor(() => expect(saveDocument).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByLabelText("Report version")).toHaveProperty("value", june.id));
  });

  it("finalizes after a passing review, then batch-generates only selected missing formats", async () => {
    let current = report("ready", "2026-07-31", "READY_TO_FINALIZE");
    vi.spyOn(api, "listProducts").mockResolvedValue([product3033]);
    vi.spyOn(api, "listReports").mockImplementation(async () => [current]);
    vi.spyOn(api, "getReport").mockImplementation(async () => current);
    vi.spyOn(api, "review").mockResolvedValue({ ready: true, blocking: [], warnings: [] });
    const finalize = vi.spyOn(api, "finalize").mockImplementation(async () => {
      current = report("ready", "2026-07-31", "FINALIZED");
      return current;
    });
    const renderOutputs = vi.spyOn(api, "render").mockResolvedValue([
      { id: "pdf-job", format: "pdf", status: "SUCCEEDED", progress: 100, stage: "complete", error: null, artifact_id: "pdf-artifact" },
      { id: "html-job", format: "html", status: "SUCCEEDED", progress: 100, stage: "complete", error: null, artifact_id: "html-artifact" },
    ]);

    render(<App />);
    const reviewButton = await screen.findByRole("button", { name: "Review & finalize" });
    fireEvent.click(reviewButton);

    await waitFor(() => expect(finalize).toHaveBeenCalledTimes(1));
    expect(renderOutputs).not.toHaveBeenCalled();
    const html = await screen.findByLabelText("HTML");
    expect((screen.getByLabelText("PDF") as HTMLInputElement).checked).toBe(true);
    fireEvent.click(html);
    fireEvent.click(screen.getByRole("button", { name: "Generate selected" }));

    await waitFor(() => expect(renderOutputs).toHaveBeenCalledWith("ready", ["pdf", "html"]));
  });
});
