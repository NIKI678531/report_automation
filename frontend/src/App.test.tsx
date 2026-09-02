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
  window.history.replaceState({}, "", "/");
});

const product3033: Product = {
  id: "product-3033",
  product_code: "3033",
  ticker: "3033.HK",
  name_en: "CSOP Hang Seng TECH Index ETF",
  name_zh_hans: "南方东英恒生科技指数ETF",
  name_zh_hant: "南方東英恒生科技指數ETF",
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
  const monthName = languageMode === "ZH_HANS" || languageMode === "ZH_HANT"
    ? `${Number(reportDate.slice(5, 7))}月`
    : new Date(`${reportDate}T00:00:00Z`).toLocaleDateString("en-HK", { month: "long", timeZone: "UTC" });
  return {
    id,
    product_code: "3033",
    product_name: languageMode === "ZH_HANS" ? "南方东英恒生科技指数ETF (3033.HK)" : languageMode === "ZH_HANT" ? "南方東英恒生科技指數ETF (3033.HK)" : "CSOP Hang Seng TECH Index ETF (3033.HK)",
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
          month_in_review: { title: languageMode === "ZH_HANS" ? `${monthName}月度回顾` : languageMode === "ZH_HANT" ? `${monthName}月度回顧` : `${monthName} in Review`, display_title: languageMode === "ZH_HANS" ? `${monthName}月度回顾` : languageMode === "ZH_HANT" ? `${monthName}月度回顧` : `${monthName} in Review`, summary: "", drivers: [], monitor: [], outlook: "" },
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

function renderAt(path: string, withLocale = false) {
  window.history.replaceState({}, "", path);
  return render(withLocale ? <LocaleProvider><App /></LocaleProvider> : <App />);
}

describe("report center navigation", () => {
  it("opens the report center without loading or refreshing an individual report", async () => {
    const augustDraft = report("august-draft", "2026-08-31", "DRAFT");
    const augustFinal = report("august-final", "2026-08-31", "FINALIZED");
    const julyArchived = report("july-archived", "2026-07-31", "ARCHIVED");
    vi.spyOn(api, "listReports").mockResolvedValue([augustDraft, augustFinal, julyArchived]);
    const getReport = vi.spyOn(api, "getReport");
    const refreshAutomaticData = vi.spyOn(api, "refreshAutomaticData");

    renderAt("/", true);

    expect(await screen.findByRole("heading", { name: "Report center" })).toBeTruthy();
    expect(screen.getAllByText("August 2026").length).toBeGreaterThan(0);
    expect(screen.getByText("DRAFT")).toBeTruthy();
    expect(screen.getByText("FINALIZED")).toBeTruthy();
    expect(screen.queryByLabelText("Report year")).toBeNull();
    expect(getReport).not.toHaveBeenCalled();
    expect(refreshAutomaticData).not.toHaveBeenCalled();
    expect(api.listReports).toHaveBeenCalledWith({ includeArchived: true });

    const archive = screen.getByText("Archived reports").closest("details");
    expect(archive?.hasAttribute("open")).toBe(false);

    fireEvent.change(screen.getByLabelText("Language"), { target: { value: "zh-Hans" } });
    expect(await screen.findByRole("heading", { name: "报告中心" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("语言"), { target: { value: "zh-Hant" } });
    expect(await screen.findByRole("heading", { name: "報告中心" })).toBeTruthy();
  });

  it("opens the exact report selected from the report center", async () => {
    const july = report("july", "2026-07-31", "EDITING");
    const august = report("august", "2026-08-31", "DRAFT");
    vi.spyOn(api, "listProducts").mockResolvedValue([product3033]);
    vi.spyOn(api, "listReports").mockResolvedValue([august, july]);
    const getReport = vi.spyOn(api, "getReport").mockImplementation(async (id) => id === july.id ? july : august);
    vi.spyOn(api, "refreshAutomaticData").mockResolvedValue({ changed: false });

    renderAt("/", true);
    fireEvent.click(await screen.findByRole("button", { name: "Open English report for 2026-07-31, EDITING" }));

    await waitFor(() => expect(window.location.pathname).toBe(`/reports/${july.id}`));
    await waitFor(() => expect(getReport).toHaveBeenCalledWith(july.id));
    expect(screen.getByLabelText("Report month")).toHaveProperty("value", "07");
  });

  it("opens archived reports in a read-only workspace", async () => {
    const archived = report("archived", "2026-07-31", "ARCHIVED");
    const archivedChinese = report("archived-chinese", "2026-07-31", "ARCHIVED", 1, "ZH_HANS");
    archived.finalized_document_version = 1;
    archived.artifacts = [{ id: "pdf", format: "pdf", size_bytes: 10, checksum: "pdf", is_current: false }];
    vi.spyOn(api, "listProducts").mockResolvedValue([product3033]);
    vi.spyOn(api, "listReports").mockResolvedValue([archived, archivedChinese]);
    vi.spyOn(api, "getReport").mockImplementation(async (id) => id === archivedChinese.id ? archivedChinese : archived);

    renderAt(`/reports/${archived.id}`, true);

    expect(await screen.findByText("Archived · read-only")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Delete report" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Review & finalize" })).toBeNull();
    expect(screen.getByRole("button", { name: "Assisted draft" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Downloads" })).toHaveProperty("disabled", false);

    fireEvent.change(screen.getByLabelText("Language"), { target: { value: "zh-Hans" } });
    await waitFor(() => expect(window.location.pathname).toBe("/reports/" + archivedChinese.id));
  });

  it("shows a not-found state for an unknown report URL", async () => {
    vi.spyOn(api, "listReports").mockResolvedValue([]);
    vi.spyOn(api, "getReport").mockRejectedValue(new Error("Report not found."));

    renderAt("/reports/missing", true);

    expect(await screen.findByRole("heading", { name: "Report not found" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Back to reports" })).toBeTruthy();
  });
});

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

    renderAt("/reports/new");

    await waitFor(() => expect(screen.getByLabelText("Fund 3033")).toBeTruthy());
    expect(screen.getByText("CSOP Hang Seng TECH Index ETF")).toBeTruthy();
    expect(screen.queryByRole("combobox", { name: "Fund" })).toBeNull();
    expect(screen.getByLabelText("Report year").getAttribute("type")).toBe("number");
    expect(screen.getByLabelText("Report year").getAttribute("min")).toBe("1000");
    expect(screen.getByLabelText("Report year").getAttribute("max")).toBe("9999");
    expect(screen.getByLabelText("Report month").tagName).toBe("SELECT");
  });

  it("opens the exact report selected by its URL", async () => {
    const july = report("july", "2026-07-31", "EDITING", 1);
    const december = report("december-r2", "2025-12-31", "DRAFT", 2);
    vi.spyOn(api, "listProducts").mockResolvedValue([product3033]);
    vi.spyOn(api, "listReports").mockResolvedValue([july, december]);
    vi.spyOn(api, "getReport").mockImplementation(async (id) => id === december.id ? december : july);
    vi.spyOn(api, "refreshAutomaticData").mockResolvedValue({ changed: false });

    renderAt(`/reports/${december.id}`);

    await waitFor(() => expect(screen.getByLabelText("Report version")).toHaveProperty("value", december.id));
    expect(screen.getByLabelText("Report year")).toHaveProperty("value", "2025");
    expect(screen.getByLabelText("Report month")).toHaveProperty("value", "12");
    expect(api.refreshAutomaticData).toHaveBeenCalledWith(december.id, december.version);
    expect(api.getReport).toHaveBeenCalledWith(december.id);
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

    renderAt(`/reports/${july.id}`);
    await waitFor(() => expect(screen.getByRole("button", { name: /Footnotes & Disclosures/ })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Footnotes & Disclosures/ }));
    const footnote = await screen.findByLabelText("Historical footnote");
    fireEvent.change(footnote, { target: { value: "Reviewed disclosure" } });
    fireEvent.change(screen.getByLabelText("Report month"), { target: { value: "06" } });

    await waitFor(() => expect(saveDocument).toHaveBeenCalled());
    await waitFor(() => expect(window.location.pathname).toBe(`/reports/${june.id}`));
    await waitFor(() => expect(screen.getByLabelText("Report version")).toHaveProperty("value", june.id));
  });

  it("stays in the workspace when pending edits cannot be saved", async () => {
    const july = report("july-save-error", "2026-07-31", "EDITING");
    vi.spyOn(api, "listProducts").mockResolvedValue([product3033]);
    vi.spyOn(api, "listReports").mockResolvedValue([july]);
    vi.spyOn(api, "getReport").mockResolvedValue(july);
    vi.spyOn(api, "refreshAutomaticData").mockResolvedValue({ changed: false });
    vi.spyOn(api, "saveDocument").mockRejectedValue(new Error("Save failed."));

    renderAt("/reports/" + july.id);
    fireEvent.click(await screen.findByRole("button", { name: /Footnotes & Disclosures/ }));
    fireEvent.change(await screen.findByLabelText("Historical footnote"), { target: { value: "Unsaved disclosure" } });
    fireEvent.click(screen.getByRole("button", { name: "Report center" }));

    expect((await screen.findByRole("alert")).textContent).toContain("Save failed.");
    expect(window.location.pathname).toBe("/reports/" + july.id);
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

    renderAt(`/reports/${saved.id}`);

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

    renderAt(`/reports/${current.id}`);
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

    renderAt("/reports/new?month=2026-06&language=EN");
    fireEvent.click(await screen.findByRole("button", { name: "Create another report" }));

    await waitFor(() => expect(create).toHaveBeenCalledWith("2026-06-30", "3033", "EN"));
    await waitFor(() => expect(window.location.pathname).toBe(`/reports/${created.id}`));
    await waitFor(() => expect(screen.getByLabelText("Report version")).toHaveProperty("value", created.id));
  });

  it("creates and synchronizes language variants while keeping the active module", async () => {
    const english = report("english", "2026-06-30", "DRAFT", 1, "EN");
    const chinese = report("chinese", "2026-06-30", "DRAFT", 1, "ZH_HANS");
    const traditional = report("traditional", "2026-06-30", "DRAFT", 1, "ZH_HANT");
    let visibleReports = [english];
    vi.spyOn(api, "listProducts").mockResolvedValue([product3033]);
    vi.spyOn(api, "listReports").mockImplementation(async () => visibleReports);
    vi.spyOn(api, "getReport").mockImplementation(async (id) => id === chinese.id ? chinese : id === traditional.id ? traditional : english);
    vi.spyOn(api, "refreshAutomaticData").mockResolvedValue({ changed: false });
    const createVariant = vi.spyOn(api, "createLanguageVariant").mockImplementation(async (_sourceId, mode) => {
      const created = mode === "ZH_HANT" ? traditional : chinese;
      visibleReports = [...visibleReports.filter((item) => item.id !== created.id), created];
      return created;
    });
    const syncVariant = vi.spyOn(api, "syncLanguageVariant").mockImplementation(async (_sourceId, targetId) => (
      targetId === chinese.id ? chinese : targetId === traditional.id ? traditional : english
    ));

    renderAt(`/reports/${english.id}`, true);
    const language = await screen.findByLabelText("Language");
    fireEvent.click(screen.getByRole("button", { name: /Footnotes & Disclosures/ }));
    fireEvent.change(language, { target: { value: "zh-Hans" } });

    await waitFor(() => expect(createVariant).toHaveBeenCalledWith(english.id, "ZH_HANS", 1));
    await waitFor(() => expect(syncVariant).toHaveBeenCalledWith(english.id, chinese.id, 1, 1));
    await waitFor(() => expect(screen.getByText("月度评论")).toBeTruthy());
    expect(screen.getByRole("button", { name: /脚注与披露/ }).getAttribute("aria-current")).toBe("page");
    expect(window.localStorage.getItem("commentary.locale")).toBe("zh-Hans");

    fireEvent.change(screen.getByLabelText("语言"), { target: { value: "en" } });
    await waitFor(() => expect(syncVariant).toHaveBeenCalledWith(chinese.id, english.id, 1, 1));
    expect(screen.getByRole("button", { name: /Footnotes & Disclosures/ }).getAttribute("aria-current")).toBe("page");

    fireEvent.change(screen.getByLabelText("Language"), { target: { value: "zh-Hant" } });
    await waitFor(() => expect(createVariant).toHaveBeenCalledWith(english.id, "ZH_HANT", 1));
    await waitFor(() => expect(syncVariant).toHaveBeenCalledWith(english.id, traditional.id, 1, 1));
    await waitFor(() => expect(screen.getByText("月度評論")).toBeTruthy());
    expect(screen.getByRole("button", { name: /註腳與披露/ }).getAttribute("aria-current")).toBe("page");
    expect(window.localStorage.getItem("commentary.locale")).toBe("zh-Hant");
  });

  it.each([
    ["DRAFT" as const, "draft"],
    ["FINALIZED" as const, "finalized"],
  ])("deletes a selected %s report and returns to the report center", async (status, id) => {
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

    renderAt(`/reports/${target.id}`);
    fireEvent.click(await screen.findByRole("button", { name: "Delete report" }));

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining(`${target.report_date} revision ${target.revision}`));
    await waitFor(() => expect(deleteSelected).toHaveBeenCalledWith(target.id, target.version));
    await waitFor(() => expect(window.location.pathname).toBe("/"));
    expect(await screen.findByRole("heading", { name: "Report center" })).toBeTruthy();
  });
});
