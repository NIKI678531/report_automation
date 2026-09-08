// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type Report } from "../api";
import { LocaleProvider, type Locale } from "../i18n";
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
  language_mode: "EN",
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
      product_ticker: "3033.HK",
      next_rebalancing_date: "2026-09-04",
      next_rebalancing_date_source: "SNAPSHOT",
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
          portfolio: [
            { metric_code: "AUM", label: "Asset Under Management (HKD)^", raw_value: "67536.55", display_value: "67,536.55 million" },
            { metric_code: "AVERAGE_DAILY_TURNOVER", label: "Average Daily Turnover (HKD)^^", raw_value: "12882", display_value: "12,882 million" },
            { metric_code: "NUMBER_OF_HOLDINGS", label: "Number of holdings", raw_value: "1", display_value: "1" },
          ],
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

    expect(screen.getByRole("heading", { name: "The Performance of 3033.HK Constituents" })).toBeTruthy();
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
    const calculate = vi.spyOn(api, "calculate").mockResolvedValue({
      snapshot_id: "snapshot-1", formula_version: "hstech-2026.1", metrics: {}, document_version: 5, quality_results: [],
    });

    render(<ReportModule report={report} active="analytics" busy={false} run={run} />);

    expect(screen.queryByRole("button", { name: /Upload file/i })).toBeNull();
    expect(screen.getByText("Top 10 3033.HK Constituents")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "3033.HK Sectors Breakdown" })).toBeTruthy();
    expect(screen.getByRole("img", { name: /3033\.HK Sectors Breakdown/i })).toBeTruthy();
    expect(screen.getByText(/Derived by the backend from the active constituent snapshot/i)).toBeTruthy();
    expect(screen.getByText("Asset Under Management (HKD)^")).toBeTruthy();
    expect(screen.getByText("67,536.55 million").closest("data")?.getAttribute("value")).toBe("67536.55");
    expect(screen.getByText("Average Daily Turnover (HKD)^^")).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Average Daily Turnover (HKD)^^" })).toHaveProperty("value", "12,882 million");
    fireEvent.click(screen.getByRole("button", { name: "Refresh analytics" }));
    await waitFor(() => expect(calculate).toHaveBeenCalledWith(report.id));
  });

  it.each([
    { locale: "zh-Hans", languageMode: "ZH_HANS", constituent: "3033.HK 成分股表现", top10: "3033.HK 十大成分股", sectors: "3033.HK 行业分布" },
    { locale: "zh-Hant", languageMode: "ZH_HANT", constituent: "3033.HK 成分股表現", top10: "3033.HK 十大成分股", sectors: "3033.HK 行業分佈" },
  ] as const)("uses the product ticker in $locale web headings", async ({ locale, languageMode, constituent, top10, sectors }) => {
    vi.spyOn(api, "listDatasets").mockResolvedValue([]);
    const localizedReport = { ...report, language_mode: languageMode } as Report;
    const { rerender } = render(
      <LocaleProvider locale={locale as Locale}>
        <ReportModule report={localizedReport} active="constituents" busy={false} run={run} />
      </LocaleProvider>,
    );
    expect(screen.getByRole("heading", { name: constituent })).toBeTruthy();

    rerender(
      <LocaleProvider locale={locale as Locale}>
        <ReportModule report={localizedReport} active="analytics" busy={false} run={run} />
      </LocaleProvider>,
    );
    expect(screen.getByText(top10)).toBeTruthy();
    expect(screen.getByRole("heading", { name: sectors })).toBeTruthy();
    expect(screen.getByRole("img", { name: new RegExp(sectors.replace(".", "\\.")) })).toBeTruthy();
  });

  it("keeps the AUM and turnover rows visible for a legacy holding-only document", () => {
    vi.spyOn(api, "listDatasets").mockResolvedValue([]);
    const legacyReport = structuredClone(report);
    const content = legacyReport.latest_document?.content as Record<string, unknown>;
    const sections = content.sections as Record<string, Record<string, unknown>>;
    sections.analytics.portfolio = [
      { label: "Number of holdings", value: "30" },
    ];

    render(<ReportModule report={legacyReport} active="analytics" busy={false} run={run} />);

    expect(screen.getByText("Asset Under Management (HKD)^")).toBeTruthy();
    expect(screen.getByText("Average Daily Turnover (HKD)^^")).toBeTruthy();
    expect(screen.getAllByText("N/A")).toHaveLength(1);
    expect(screen.getByRole("textbox", { name: "Average Daily Turnover (HKD)^^" })).toHaveProperty("value", "NA");
    expect(screen.getByText("Number of holdings").nextElementSibling?.textContent).toBe("30");
  });

  it.each([
    { reportDate: "2024-02-29", monthName: "February", aum: "51,234.10 million", turnover: "8,765 million" },
    { reportDate: "2026-08-31", monthName: "August", aum: "72,345.67 million", turnover: "13,210 million" },
    { reportDate: "2030-12-31", monthName: "December", aum: "88,000.00 million", turnover: "14,500 million" },
  ])("renders the selected $monthName report's own Portfolio Analysis values", ({ reportDate, monthName, aum, turnover }) => {
    vi.spyOn(api, "listDatasets").mockResolvedValue([]);
    const monthlyReport = structuredClone(report);
    monthlyReport.id = `report-${reportDate}`;
    monthlyReport.report_date = reportDate;
    const content = monthlyReport.latest_document?.content as Record<string, unknown>;
    content.month_name = monthName;
    const sections = content.sections as Record<string, Record<string, unknown>>;
    sections.analytics.portfolio = [
      { metric_code: "AUM", label: "Asset Under Management (HKD)^", raw_value: aum.replaceAll(",", "").split(" ")[0], display_value: aum },
      { metric_code: "AVERAGE_DAILY_TURNOVER", label: "Average Daily Turnover (HKD)^^", raw_value: turnover.replaceAll(",", "").split(" ")[0], display_value: turnover },
      { metric_code: "NUMBER_OF_HOLDINGS", label: "Number of holdings", raw_value: "30", display_value: "30" },
    ];

    render(<ReportModule report={monthlyReport} active="analytics" busy={false} run={run} />);

    expect(screen.getByText(aum)).toBeTruthy();
    expect(screen.getByDisplayValue(turnover)).toBeTruthy();
    expect(screen.getByText(`Performers in ${monthName}`)).toBeTruthy();
  });

  it("saves only the 3033 turnover display text without changing any other report data", async () => {
    vi.spyOn(api, "listDatasets").mockResolvedValue([]);
    const saveDocument = vi.spyOn(api, "saveDocument").mockResolvedValue({ version: 5 });
    const original = structuredClone(report);
    render(<ReportModule report={report} active="analytics" busy={false} run={run} />);

    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toHaveProperty("disabled", true);
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    fireEvent.change(screen.getByRole("textbox", { name: "Average Daily Turnover (HKD)^^" }), { target: { value: "9,876 million" } });
    fireEvent.click(save);

    const expected = structuredClone(report.latest_document!.content);
    const sections = expected.sections as Record<string, Record<string, unknown>>;
    const portfolio = sections.analytics.portfolio as Record<string, unknown>[];
    portfolio[1] = { ...portfolio[1], display_value: "9,876 million", value: "9,876 million" };
    await waitFor(() => expect(saveDocument).toHaveBeenCalledExactlyOnceWith(report.id, report.latest_document!.version, expected));
    expect(report).toEqual(original);
  });

  it.each([
    { stored: { display_value: null }, expected: "NA" },
    { stored: { display_value: "" }, expected: "NA" },
    { stored: { display_value: "   " }, expected: "NA" },
    { stored: { display_value: "N/A" }, expected: "NA" },
    { stored: {}, expected: "NA" },
    { stored: { display_value: 0 }, expected: "0" },
    { stored: { display_value: "0" }, expected: "0" },
    { stored: { value: "1,234 million" }, expected: "1,234 million" },
  ])("prefills turnover as $expected from $stored without saving a default", ({ stored, expected }) => {
    vi.spyOn(api, "listDatasets").mockResolvedValue([]);
    const saveDocument = vi.spyOn(api, "saveDocument").mockResolvedValue({ version: 5 });
    const missingReport = structuredClone(report);
    const sections = missingReport.latest_document!.content.sections as Record<string, Record<string, unknown>>;
    sections.analytics.portfolio = [{ metric_code: "AVERAGE_DAILY_TURNOVER", ...stored }];
    render(<ReportModule report={missingReport} active="analytics" busy={false} run={run} />);

    expect(screen.getByRole("textbox")).toHaveProperty("value", expected);
    expect(screen.getByRole("button", { name: "Save" })).toHaveProperty("disabled", true);
    expect(saveDocument).not.toHaveBeenCalled();
  });

  it.each(["", "   "])("saves an emptied turnover as NA (%j)", async (value) => {
    vi.spyOn(api, "listDatasets").mockResolvedValue([]);
    const saveDocument = vi.spyOn(api, "saveDocument").mockResolvedValue({ version: 5 });
    render(<ReportModule report={report} active="analytics" busy={false} run={run} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value } });
    expect(screen.getByRole("textbox")).toHaveProperty("value", value);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(saveDocument).toHaveBeenCalledOnce());
    const sections = saveDocument.mock.calls[0][2].sections as Record<string, Record<string, unknown>>;
    expect((sections.analytics.portfolio as Record<string, unknown>[])[1]).toEqual(expect.objectContaining({ display_value: "NA", value: "NA", raw_value: "12882" }));
  });

  it.each([false, true])("saves legacy portfolio turnover without normalizing other rows (existing: %j)", async (existing) => {
    vi.spyOn(api, "listDatasets").mockResolvedValue([]);
    const saveDocument = vi.spyOn(api, "saveDocument").mockResolvedValue({ version: 5 });
    const legacyReport = structuredClone(report);
    const sections = legacyReport.latest_document!.content.sections as Record<string, Record<string, unknown>>;
    const holdings = { label: "Number of holdings", value: "30" };
    sections.analytics.portfolio = existing ? [holdings, { label: "Average Daily Turnover (HKD)^^", value: "100 million" }] : [holdings];
    render(<ReportModule report={legacyReport} active="analytics" busy={false} run={run} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "200 million" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(saveDocument).toHaveBeenCalledOnce());
    const savedSections = saveDocument.mock.calls[0][2].sections as Record<string, Record<string, unknown>>;
    const savedPortfolio = savedSections.analytics.portfolio as Record<string, unknown>[];
    expect(savedPortfolio).toHaveLength(2);
    expect(savedPortfolio[0]).toEqual(holdings);
    expect(savedPortfolio[1]).toEqual(expect.objectContaining({ label: "Average Daily Turnover (HKD)^^", display_value: "200 million", value: "200 million" }));
    expect({ ...savedSections.analytics, portfolio: sections.analytics.portfolio }).toEqual(sections.analytics);
  });

  it("registers only dirty turnover for navigation saves and clears it on unmount", async () => {
    vi.spyOn(api, "listDatasets").mockResolvedValue([]);
    const saveDocument = vi.spyOn(api, "saveDocument").mockResolvedValue({ version: 5 });
    const registerPendingSave = vi.fn<(save: (() => Promise<void>) | null) => void>();
    const { unmount } = render(<ReportModule report={report} active="analytics" busy={false} run={run} registerPendingSave={registerPendingSave} />);
    expect(registerPendingSave).toHaveBeenLastCalledWith(null);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "123 million" } });
    const pending = registerPendingSave.mock.lastCall![0];
    expect(pending).toBeTypeOf("function");
    await pending!();
    expect(saveDocument).toHaveBeenCalledOnce();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "12,882 million" } });
    expect(registerPendingSave).toHaveBeenLastCalledWith(null);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "456 million" } });
    unmount();
    expect(registerPendingSave).toHaveBeenLastCalledWith(null);
  });

  it.each([
    { saved: false, fresh: "456 million", expected: "456 million" },
    { saved: true, fresh: "456 million", expected: "456 million" },
    { saved: false, fresh: "N/A", expected: "NA" },
    { saved: true, fresh: "N/A", expected: "NA" },
  ])("restores returned $expected after Refresh analytics (saved: $saved)", async ({ saved, fresh, expected }) => {
    vi.spyOn(api, "listDatasets").mockResolvedValue([]);
    const saveDocument = vi.spyOn(api, "saveDocument").mockResolvedValue({ version: 5 });
    const calculate = vi.spyOn(api, "calculate").mockResolvedValue({
      snapshot_id: "snapshot-1", formula_version: "hstech-2026.1", metrics: {}, document_version: 6, quality_results: [],
    });
    const registerPendingSave = vi.fn<(save: (() => Promise<void>) | null) => void>();
    const { rerender } = render(<ReportModule report={report} active="analytics" busy={false} run={run} registerPendingSave={registerPendingSave} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "123 million" } });
    if (saved) {
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(saveDocument).toHaveBeenCalledOnce());
      const savedReport = structuredClone(report);
      savedReport.latest_document!.version = 5;
      savedReport.latest_document!.content = saveDocument.mock.calls[0][2];
      rerender(<ReportModule report={savedReport} active="analytics" busy={false} run={run} registerPendingSave={registerPendingSave} />);
      expect(screen.getByRole("textbox")).toHaveProperty("value", "123 million");
      expect(screen.getByRole("button", { name: "Save" })).toHaveProperty("disabled", true);
    }
    fireEvent.click(screen.getByRole("button", { name: "Refresh analytics" }));
    await waitFor(() => expect(calculate).toHaveBeenCalledWith(report.id));
    const refreshedReport = structuredClone(report);
    refreshedReport.latest_document!.version = 6;
    const sections = refreshedReport.latest_document!.content.sections as Record<string, Record<string, unknown>>;
    (sections.analytics.portfolio as Record<string, unknown>[])[1].display_value = fresh;
    rerender(<ReportModule report={refreshedReport} active="analytics" busy={false} run={run} registerPendingSave={registerPendingSave} />);

    expect(screen.getByRole("textbox")).toHaveProperty("value", expected);
    expect(screen.getByRole("button", { name: "Save" })).toHaveProperty("disabled", true);
    expect(registerPendingSave).toHaveBeenLastCalledWith(null);
    expect(saveDocument).toHaveBeenCalledTimes(saved ? 1 : 0);
  });

  it.each(["Save", "Refresh analytics"])("retains the turnover draft when %s fails", async (action) => {
    vi.spyOn(api, "listDatasets").mockResolvedValue([]);
    vi.spyOn(api, "saveDocument").mockRejectedValue(new Error("Save failed"));
    vi.spyOn(api, "calculate").mockRejectedValue(new Error("Refresh failed"));
    const onError = vi.fn();
    const failedRun = async (work: () => Promise<unknown>) => { try { await work(); } catch (caught) { onError(String(caught)); } };
    render(<ReportModule report={report} active="analytics" busy={false} run={failedRun} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "123 million" } });
    fireEvent.click(screen.getByRole("button", { name: action }));
    await waitFor(() => expect(onError).toHaveBeenCalledOnce());
    expect(screen.getByRole("textbox")).toHaveProperty("value", "123 million");
    expect(screen.getByRole("button", { name: "Save" })).toHaveProperty("disabled", false);
  });

  it.each([
    { status: "FINALIZED", busy: false, document: true },
    { status: "ARCHIVED", busy: false, document: true },
    { status: "EDITING", busy: true, document: true },
    { status: "EDITING", busy: false, document: false },
  ] as const)("disables turnover edits for $status (busy: $busy, document: $document)", ({ status, busy, document }) => {
    vi.spyOn(api, "listDatasets").mockResolvedValue([]);
    const frozenReport = { ...report, status, latest_document: document ? report.latest_document : null };
    render(<ReportModule report={frozenReport} active="analytics" busy={busy} run={run} />);
    expect(screen.getByRole("textbox")).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Save" })).toHaveProperty("disabled", true);
  });

  it("resets the draft for another report and keeps other products read-only", () => {
    vi.spyOn(api, "listDatasets").mockResolvedValue([]);
    const { rerender } = render(<ReportModule report={report} active="analytics" busy={false} run={run} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "123 million" } });
    rerender(<ReportModule report={{ ...report, id: "report-2" }} active="analytics" busy={false} run={run} />);
    expect(screen.getByRole("textbox")).toHaveProperty("value", "12,882 million");
    rerender(<ReportModule report={{ ...report, product_code: "3037" }} active="analytics" busy={false} run={run} />);
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.getByText("12,882 million")).toBeTruthy();
  });

  it("uses the selected month as the summary title and saves block alignment without a duplicate title field", async () => {
    const saveDocument = vi.spyOn(api, "saveDocument").mockResolvedValue({ version: 5 });

    render(<ReportModule report={report} active="review" busy={false} run={run} />);

    expect(screen.queryByLabelText("Month in Review title")).toBeNull();
    expect(screen.getByLabelText("Title for summary block")).toHaveProperty("value", "June in Review");
    fireEvent.click(screen.getAllByTitle("Align center")[0]);
    fireEvent.click(screen.getByRole("button", { name: "Save layout" }));

    await waitFor(() => expect(saveDocument).toHaveBeenCalledWith(
      report.id,
      report.latest_document?.version,
      expect.objectContaining({
        sections: expect.objectContaining({
          month_in_review: expect.objectContaining({
            title: "June in Review",
            display_title: "June in Review",
            blocks: expect.arrayContaining([expect.objectContaining({ block_id: "summary", text_align: "center" })]),
          }),
        }),
      }),
    ));
  });

  it("edits and saves the next rebalancing date as a manual document override", async () => {
    vi.spyOn(api, "listDatasets").mockResolvedValue([]);
    const saveDocument = vi.spyOn(api, "saveDocument").mockResolvedValue({ version: 5 });

    render(<ReportModule report={report} active="constituents" busy={false} run={run} />);

    expect(screen.getByText("(*Next Rebalancing Date: 4 September 2026)")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Next rebalancing date"), { target: { value: "2026-10-15" } });
    fireEvent.click(screen.getByRole("button", { name: "Save date" }));

    await waitFor(() => expect(saveDocument).toHaveBeenCalledWith(
      report.id,
      report.latest_document?.version,
      expect.objectContaining({ next_rebalancing_date: "2026-10-15", next_rebalancing_date_source: "MANUAL" }),
    ));
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
