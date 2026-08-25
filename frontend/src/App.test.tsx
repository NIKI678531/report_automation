// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App, { needsAutomaticBackfill } from "./App";
import { api, type Product, type Report } from "./api";
import { LocaleProvider, type ReportLanguage } from "./i18n";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

const product3033: Product = {
  id: "product-3033",
  product_code: "3033",
  ticker: "3033.HK",
  name_en: "CSOP Hang Seng TECH Index ETF",
  name_zh_hans: "南方东英恒生科技指数ETF",
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

function report(id: string, reportDate: string, status: Report["status"] = "DRAFT", revision = 1, languageMode: ReportLanguage = "EN"): Report {
  const monthName = languageMode === "ZH_HANS"
    ? `${Number(reportDate.slice(5, 7))}月`
    : new Date(`${reportDate}T00:00:00Z`).toLocaleDateString("en-HK", { month: "long", timeZone: "UTC" });
  return {
    id,
    product_code: "3033",
    product_name: languageMode === "ZH_HANS" ? "南方东英恒生科技指数ETF (3033.HK)" : "CSOP Hang Seng TECH Index ETF (3033.HK)",
    constituent_index_code: "HSTECH",
    benchmark_instrument_code: "HSTECHN",
    benchmark_code: "HSTECH",
    report_date: reportDate,
    language_mode: languageMode,
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
          month_in_review: { title: languageMode === "ZH_HANS" ? `${monthName}月度回顾` : `${monthName} in Review`, display_title: languageMode === "ZH_HANS" ? `${monthName}月度回顾` : `${monthName} in Review`, summary: "", drivers: [], monitor: [], outlook: "" },
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
  it("backfills Final Analytics for any report month when constituents are already present", () => {
    for (const reportDate of ["2026-02-28", "2026-06-30", "2026-08-31"]) {
      const legacy = report(`legacy-${reportDate}`, reportDate, "EDITING");
      const sections = legacy.latest_document?.content.sections as Record<string, unknown>;
      sections.constituents = [{ security_code: "1", weight: "1", return_1m: "0.1" }];
      sections.historical_performance = { rows: [{ period: "1M" }] };
      expect(needsAutomaticBackfill(legacy)).toBe(true);

      (sections.analytics as Record<string, unknown>).top10 = [{ security_code: "1" }];
      (sections.analytics as Record<string, unknown>).portfolio = [
        { label: "Number of holdings", value: "1" },
      ];
      expect(needsAutomaticBackfill(legacy)).toBe(true);

      (sections.analytics as Record<string, unknown>).portfolio = [
        { label: "Asset Under Management (HKD)^", value: "1,000.00 million" },
        { label: "Average Daily Turnover (HKD)^^", value: "50 million" },
        { label: "Number of holdings", value: "1" },
      ];
      expect(needsAutomaticBackfill(legacy)).toBe(false);
    }
  });

  it("renders a fixed 3033 header instead of a fund dropdown", async () => {
    vi.spyOn(api, "listProducts").mockResolvedValue([product3033]);
    vi.spyOn(api, "listReports").mockResolvedValue([]);

    render(<App />);

    await waitFor(() => expect(screen.getByLabelText("Fund 3033")).toBeTruthy());
    expect(screen.getByText("CSOP Hang Seng TECH Index ETF")).toBeTruthy();
    expect(screen.queryByRole("combobox", { name: "Fund" })).toBeNull();
    expect(screen.getByLabelText("Report year").getAttribute("type")).toBe("number");
    expect(screen.getByLabelText("Report year").getAttribute("min")).toBe("1000");
    expect(screen.getByLabelText("Report year").getAttribute("max")).toBe("9999");
    expect(screen.getByLabelText("Report month").tagName).toBe("SELECT");
  });

  it("switches directly to the newest production draft for any selected month", async () => {
    const july = report("july", "2026-07-31", "EDITING", 1);
    const december = report("december-r2", "2025-12-31", "DRAFT", 2);
    vi.spyOn(api, "listProducts").mockResolvedValue([product3033]);
    vi.spyOn(api, "listReports").mockResolvedValue([july, december]);
    vi.spyOn(api, "getReport").mockImplementation(async (id) => id === december.id ? december : july);
    vi.spyOn(api, "refreshAutomaticData").mockResolvedValue({ changed: false });

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText("Report year")).toHaveProperty("value", "2026"));
    expect(screen.getByLabelText("Report month")).toHaveProperty("value", "07");

    fireEvent.change(screen.getByLabelText("Report year"), { target: { value: "2025" } });
    await waitFor(() => expect(api.listProducts).toHaveBeenCalledWith("2025-07-31"));
    fireEvent.change(screen.getByLabelText("Report month"), { target: { value: "12" } });

    await waitFor(() => expect(screen.getByLabelText("Report version")).toHaveProperty("value", december.id));
    expect(api.refreshAutomaticData).toHaveBeenCalledWith(december.id, december.version);
    expect(screen.getByRole("option", { name: "2025-12-31 · r2 · DRAFT" })).toBeTruthy();
  });

  it("auto-saves editable disclosures before changing report month", async () => {
    const july = report("july", "2026-07-31", "EDITING");
    const june = report("june", "2026-06-30", "DRAFT");
    vi.spyOn(api, "listProducts").mockResolvedValue([product3033]);
    vi.spyOn(api, "listReports").mockResolvedValue([july, june]);
    vi.spyOn(api, "getReport").mockImplementation(async (id) => id === june.id ? june : july);
    vi.spyOn(api, "refreshAutomaticData").mockResolvedValue({ changed: false });
    const saveDocument = vi.spyOn(api, "saveDocument").mockResolvedValue({ version: 2 });

    render(<App />);
    await waitFor(() => expect(screen.getByRole("button", { name: /Footnotes & Disclosures/ })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Footnotes & Disclosures/ }));
    const footnote = await screen.findByLabelText("Historical footnote");
    fireEvent.change(footnote, { target: { value: "Reviewed disclosure" } });
    fireEvent.change(screen.getByLabelText("Report month"), { target: { value: "06" } });

    await waitFor(() => expect(saveDocument).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByLabelText("Report version")).toHaveProperty("value", june.id));
  });

  it("shows Review as ready when saved blocks exist but the legacy summary is stale", async () => {
    const saved = report("saved-review", "2026-07-31", "EDITING");
    const review = (saved.latest_document?.content.sections as Record<string, Record<string, unknown>>).month_in_review;
    review.summary = "Add monthly market review.";
    review.blocks = [
      { block_id: "custom", type: "rich_text", title: "Commentary", content: "<p>Approved monthly commentary.</p>", x: 0, y: 0, w: 12, h: 4 },
    ];
    vi.spyOn(api, "listProducts").mockResolvedValue([product3033]);
    vi.spyOn(api, "listReports").mockResolvedValue([saved]);
    vi.spyOn(api, "getReport").mockResolvedValue(saved);

    render(<App />);

    const navigation = await screen.findByRole("navigation", { name: "Report modules" });
    const reviewButton = within(navigation).getByRole("button", { name: /Review/ });
    expect(reviewButton.querySelector(".module-state")?.classList.contains("ready")).toBe(true);
  });

  it("finalizes without blocking on review findings and opens direct format downloads", async () => {
    let current = report("ready", "2026-07-31", "READY_TO_FINALIZE");
    vi.spyOn(api, "listProducts").mockResolvedValue([product3033]);
    vi.spyOn(api, "listReports").mockImplementation(async () => [current]);
    vi.spyOn(api, "getReport").mockImplementation(async () => current);
    vi.spyOn(api, "refreshAutomaticData").mockResolvedValue({ changed: false });
    const review = vi.spyOn(api, "review").mockResolvedValue({
      ready: false,
      blocking: [{ check_id: "SNAPSHOT_INCOMPLETE", fix_hint: "Upload Trading calendar." }],
      warnings: [],
    });
    const finalize = vi.spyOn(api, "finalize").mockImplementation(async () => {
      current = report("ready", "2026-07-31", "FINALIZED");
      return current;
    });
    const renderOutputs = vi.spyOn(api, "render").mockResolvedValue([
      { id: "html-job", format: "html", status: "SUCCEEDED", progress: 100, stage: "complete", error: null, artifact_id: "html-artifact" },
    ]);
    const downloadArtifact = vi.spyOn(api, "downloadArtifact").mockResolvedValue(undefined);

    render(<App />);
    const reviewButton = await screen.findByRole("button", { name: "Review & finalize" });
    fireEvent.click(reviewButton);

    await waitFor(() => expect(finalize).toHaveBeenCalledTimes(1));
    expect(review).not.toHaveBeenCalled();
    expect(renderOutputs).not.toHaveBeenCalled();
    const menu = await screen.findByRole("menu", { name: "Download report" });
    expect(within(menu).getByRole("menuitem", { name: /PDF/ })).toBeTruthy();
    expect(within(menu).getByRole("menuitem", { name: /Word/ })).toBeTruthy();
    const html = within(menu).getByRole("menuitem", { name: /HTML/ });
    fireEvent.click(html);

    await waitFor(() => expect(renderOutputs).toHaveBeenCalledWith("ready", ["html"]));
    await waitFor(() => expect(downloadArtifact).toHaveBeenCalledWith("html-artifact"));
    expect(screen.queryByText(/blocking checks/i)).toBeNull();
    expect(screen.queryByText(/SNAPSHOT_INCOMPLETE/i)).toBeNull();
  });

  it("creates another report even when the selected month already has a draft", async () => {
    const existing = report("existing", "2026-06-30", "DRAFT");
    const created = report("new-report", "2026-06-30", "DRAFT");
    vi.spyOn(api, "listProducts").mockResolvedValue([product3033]);
    vi.spyOn(api, "listReports").mockResolvedValue([existing, created]);
    vi.spyOn(api, "getReport").mockImplementation(async (id) => id === created.id ? created : existing);
    vi.spyOn(api, "refreshAutomaticData").mockResolvedValue({ changed: false });
    const create = vi.spyOn(api, "createReport").mockResolvedValue(created);

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "New report" }));

    await waitFor(() => expect(create).toHaveBeenCalledWith("2026-06-30", "3033"));
    await waitFor(() => expect(screen.getByLabelText("Report version")).toHaveProperty("value", created.id));
  });

  it("switches language without auto-creating and offers an explicit independent variant", async () => {
    const english = report("english", "2026-06-30", "DRAFT", 1, "EN");
    const chinese = report("chinese", "2026-06-30", "DRAFT", 1, "ZH_HANS");
    let visibleReports = [english];
    vi.spyOn(api, "listProducts").mockResolvedValue([product3033]);
    vi.spyOn(api, "listReports").mockImplementation(async () => visibleReports);
    vi.spyOn(api, "getReport").mockImplementation(async (id) => id === chinese.id ? chinese : english);
    vi.spyOn(api, "refreshAutomaticData").mockResolvedValue({ changed: false });
    const createVariant = vi.spyOn(api, "createLanguageVariant").mockImplementation(async () => {
      visibleReports = [english, chinese];
      return chinese;
    });

    render(<LocaleProvider><App /></LocaleProvider>);
    const language = await screen.findByLabelText("Language");
    fireEvent.change(language, { target: { value: "zh-Hans" } });

    expect(await screen.findByText("本月尚无简体中文报告")).toBeTruthy();
    expect(createVariant).not.toHaveBeenCalled();
    expect(window.localStorage.getItem("commentary.locale")).toBe("zh-Hans");
    fireEvent.click(screen.getByRole("button", { name: "创建简体中文版本" }));

    await waitFor(() => expect(createVariant).toHaveBeenCalledWith(english.id, "ZH_HANS", 1));
    await waitFor(() => expect(screen.getByText("月度评论")).toBeTruthy());
  });

  it.each([
    ["DRAFT" as const, "draft"],
    ["FINALIZED" as const, "finalized"],
  ])("deletes a selected %s report and selects the remaining report", async (status, id) => {
    const target = report(id, "2026-06-30", status, 2);
    const remaining = report("remaining", "2026-06-30", "DRAFT", 1);
    let visibleReports = [target, remaining];
    vi.spyOn(api, "listProducts").mockResolvedValue([product3033]);
    vi.spyOn(api, "listReports").mockImplementation(async () => visibleReports);
    vi.spyOn(api, "getReport").mockImplementation(async (reportId) => (
      reportId === target.id ? target : remaining
    ));
    vi.spyOn(api, "refreshAutomaticData").mockResolvedValue({ changed: false });
    const deleteSelected = vi.spyOn(api, "deleteReport").mockImplementation(async () => {
      visibleReports = [remaining];
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete report" }));

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining(`${target.report_date} revision ${target.revision}`));
    await waitFor(() => expect(deleteSelected).toHaveBeenCalledWith(target.id, target.version));
    await waitFor(() => expect(screen.getByLabelText("Report version")).toHaveProperty("value", remaining.id));
  });
});
