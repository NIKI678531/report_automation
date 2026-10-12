// @vitest-environment jsdom

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CompanyNewsWorkbench,
  buildCompanyNewsCatalogQuery,
  catalogSelectionKey,
  draftsFromSnapshot,
  mergeCatalogItems,
  publishedDateHkt,
  reportYearDateRange,
  toggleCatalogSelection,
} from "./CompanyNewsWorkbench";
import { api, type CompanyNewsCatalogItem, type Report } from "../../api";
import { LocaleProvider } from "../../i18n";

const candidate: CompanyNewsCatalogItem = {
  provider: "DA_REPORT",
  external_id: "42",
  source_name: "Reuters",
  source_name_zh: "路透",
  source_name_zh_hans: "路透",
  source_code: "reuters",
  source_url: "https://example.com/news-42",
  published_at: "2026-08-10T08:00:00Z",
  published_at_source: "published_at",
  fetched_at: "2026-08-10T09:00:00Z",
  title: "DA-Report headline",
  title_en: "DA-Report headline",
  title_zh: "DA-Report 標題",
  title_zh_hans: "DA-Report 标题",
  summary: "DA-Report summary",
  summary_en: "DA-Report summary",
  summary_zh: "DA-Report 摘要",
  summary_zh_hans: "DA-Report 摘要",
  category: "Corporate",
  region: "China",
  sentiment: "bull",
  importance_score: 88,
  model: "test-model",
};

const report: Report = {
  id: "report-1",
  product_code: "3033",
  product_name: "CSOP Hang Seng TECH Index ETF",
  constituent_index_code: "HSTECH",
  benchmark_instrument_code: "HSTECHN",
  benchmark_code: "HSTECH",
  language_mode: "EN",
  report_date: "2026-06-30",
  lane: "PRODUCTION",
  status: "DRAFT",
  revision: 1,
  version: 1,
  active_snapshot_id: null,
  finalized_document_version: null,
  latest_document: { version: 1, checksum: "checksum", content: { sections: { company_news: [] } } },
};

const companies = [
  { security_code: "700", ticker: "0700.HK", name_en: "TENCENT", name_zh_hans: "腾讯控股", name_zh_hant: "騰訊控股" },
  ...Array.from({ length: 29 }, (_, index) => ({
    security_code: String(1001 + index),
    ticker: `${String(1001 + index).padStart(4, "0")}.HK`,
    name_en: `COMPANY ${index + 1}`,
    name_zh_hans: `公司${index + 1}`,
    name_zh_hant: `公司${index + 1}`,
  })),
];

const page = {
  items: [candidate],
  total: 1,
  has_more: false,
  next_cursor: null,
  facets: {
    companies,
    sources: [{ value: "reuters", label: "Reuters", label_zh: "路透", count: 1 }],
    sentiments: { bull: 1 },
    importance: { HIGH: 1 },
    date_min: "2017-03-31",
    date_max: "2026-08-07",
  },
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("DA-Report company news catalog", () => {
  it("uses the provider and external id as stable selection identity", () => {
    expect(catalogSelectionKey(candidate)).toBe("DA_REPORT:42");
  });

  it("merges cursor pages without duplicating overlap", () => {
    const updated = { ...candidate, title: "Updated headline" };
    const next = { ...candidate, external_id: "43", title: "Next headline" };
    expect(mergeCatalogItems([candidate], [updated, next])).toEqual([updated, next]);
  });
});

describe("Company News report context", () => {
  it("derives the default catalog window from the report year without timezone conversion", () => {
    expect(reportYearDateRange("2026-06-30")).toEqual({
      fromDate: "2026-01-01",
      toDate: "2026-12-31",
    });
  });

  it("uses one catalog-query shape for initial and cursor requests", () => {
    const filters = {
      query: " Tencent ",
      companyScope: "CONSTITUENTS" as const,
      source: "reuters",
      sentiment: "bear" as const,
      fromDate: "2026-01-01",
      toDate: "2026-12-31",
      sort: "newest" as const,
    };

    expect(buildCompanyNewsCatalogQuery(filters)).toEqual({
      query: "Tencent",
      company_scope: "CONSTITUENTS",
      source: "reuters",
      sentiment: "bear",
      from_date: "2026-01-01",
      to_date: "2026-12-31",
      sort: "newest",
      cursor: undefined,
      limit: 50,
    });
    expect(buildCompanyNewsCatalogQuery({ ...filters, cursor: "page-2" })).toEqual(expect.objectContaining({
      from_date: "2026-01-01",
      to_date: "2026-12-31",
      sentiment: "bear",
      cursor: "page-2",
    }));
  });

  it("uses the HKT publication date across a UTC month boundary", () => {
    expect(publishedDateHkt("2026-05-31T16:30:00Z")).toBe("2026-06-01");
  });

  it("shows a candidate in the selected-news model immediately after selection", () => {
    const selected = toggleCatalogSelection([], candidate);
    expect(selected).toEqual([expect.objectContaining({ external_id: "42", title: "DA-Report headline" })]);
    expect(toggleCatalogSelection(selected, candidate)).toEqual([]);
  });

  it("restores only the current report's saved selections", () => {
    expect(draftsFromSnapshot([], "2026-08-31")).toEqual([]);
    expect(draftsFromSnapshot([{
      news_item_id: "local-2",
      provider: "DA_REPORT",
      external_id: "42",
      title: "Saved",
      summary: "Summary",
    }], "2026-08-31")).toEqual([
      expect.objectContaining({
        news_item_id: "local-2",
        external_id: "42",
        selectionKey: "DA_REPORT:42",
        publishedAt: "2026-08-31",
      }),
    ]);
  });
});

describe("Company News automatic catalog loading", () => {
  const run = async (work: () => Promise<unknown>) => { await work(); };

  it("loads DA-Report on mount and sends search filters to the server", async () => {
    const catalog = vi.spyOn(api, "listCompanyNewsCatalog").mockResolvedValue(page);
    const user = userEvent.setup();
    render(<CompanyNewsWorkbench report={report} busy={false} run={run} selectedSnapshot={[]} />);

    expect(await screen.findByText("DA-Report headline")).toBeTruthy();
    expect(catalog).toHaveBeenCalledWith("report-1", expect.objectContaining({
      from_date: "2026-01-01",
      to_date: "2026-12-31",
      limit: 50,
      sort: "newest",
    }));
    expect(catalog.mock.calls[0]?.[1]).not.toHaveProperty("importance");
    expect(screen.queryByLabelText("Filter by importance")).toBeNull();
    expect((screen.getByLabelText("From date") as HTMLInputElement).value).toBe("2026-01-01");
    expect((screen.getByLabelText("To date") as HTMLInputElement).value).toBe("2026-12-31");
    expect(screen.queryByRole("button", { name: /Clear filters/ })).toBeNull();

    const sentiment = screen.getByRole("group", { name: "Filter by sentiment" });
    expect(within(sentiment).getAllByRole("button").map((button) => button.textContent)).toEqual([
      "All", "Bullish", "Neutral", "Bearish",
    ]);
    await user.click(within(sentiment).getByRole("button", { name: "Bearish" }));
    await waitFor(() => expect(catalog).toHaveBeenLastCalledWith(
      "report-1",
      expect.objectContaining({ sentiment: "bear", from_date: "2026-01-01", to_date: "2026-12-31" }),
    ));
    const fromDate = screen.getByLabelText("From date") as HTMLInputElement;
    await user.clear(fromDate);
    await user.type(fromDate, "2026-02-01");
    await waitFor(() => expect(catalog).toHaveBeenLastCalledWith(
      "report-1",
      expect.objectContaining({ from_date: "2026-02-01", to_date: "2026-12-31" }),
    ));

    const companyScope = screen.getByRole("group", { name: "Company scope" });
    expect(within(companyScope).getAllByRole("button")).toHaveLength(2);
    await user.type(screen.getByLabelText("Search company news"), "Tencent");
    await waitFor(() => expect(catalog).toHaveBeenLastCalledWith(
      "report-1",
      expect.objectContaining({ query: "Tencent" }),
    ));
    await user.click(within(companyScope).getByRole("button", { name: "3033.HK constituents" }));
    await waitFor(() => expect(catalog).toHaveBeenLastCalledWith(
      "report-1",
      expect.objectContaining({ query: "Tencent", company_scope: "CONSTITUENTS" }),
    ));
    await user.click(screen.getByRole("button", { name: /Clear filters/ }));
    expect(within(companyScope).getByRole("button", { name: "All companies" }).className).toContain("active");
    await waitFor(() => {
      expect((screen.getByLabelText("From date") as HTMLInputElement).value).toBe("2026-01-01");
      expect((screen.getByLabelText("To date") as HTMLInputElement).value).toBe("2026-12-31");
      expect(within(sentiment).getByRole("button", { name: "All" }).className).toContain("active");
    });
  });

  it("disables the company filter when no constituent snapshot is available", async () => {
    vi.spyOn(api, "listCompanyNewsCatalog").mockResolvedValue({
      ...page,
      facets: { ...page.facets, companies: [] },
    });
    render(<CompanyNewsWorkbench report={report} busy={false} run={run} selectedSnapshot={[]} />);

    expect(await screen.findByText("DA-Report headline")).toBeTruthy();
    const constituentScope = screen.getByRole("button", { name: "3033.HK constituents" }) as HTMLButtonElement;
    expect(constituentScope.disabled).toBe(true);
    expect(constituentScope.getAttribute("title")).toBe("Company list unavailable");
  });

  it("shows the Simplified Chinese constituent scope and catalog content", async () => {
    window.localStorage.setItem("commentary.locale", "zh-Hans");
    vi.spyOn(api, "listCompanyNewsCatalog").mockResolvedValue(page);
    render(<LocaleProvider><CompanyNewsWorkbench report={{ ...report, language_mode: "ZH_HANS" }} busy={false} run={run} selectedSnapshot={[]} /></LocaleProvider>);

    expect(await screen.findByText("DA-Report 标题")).toBeTruthy();
    expect(screen.getByRole("button", { name: "3033.HK 成份股" })).toBeTruthy();
    expect(within(screen.getByRole("group", { name: "按情绪筛选" })).getAllByRole("button").map((button) => button.textContent)).toEqual([
      "全部", "看多", "中性", "看空",
    ]);
  });

  it("shows Traditional Chinese catalog content and Hong Kong scope copy", async () => {
    window.localStorage.setItem("commentary.locale", "zh-Hant");
    vi.spyOn(api, "listCompanyNewsCatalog").mockResolvedValue(page);
    render(<LocaleProvider><CompanyNewsWorkbench report={{ ...report, language_mode: "ZH_HANT" }} busy={false} run={run} selectedSnapshot={[]} /></LocaleProvider>);

    expect(await screen.findByText("DA-Report 標題")).toBeTruthy();
    expect(screen.getByRole("button", { name: "3033.HK 成份股" })).toBeTruthy();
    expect(screen.getByText("中國")).toBeTruthy();
    expect(within(screen.getByRole("group", { name: "按情緒篩選" })).getAllByRole("button").map((button) => button.textContent)).toEqual([
      "全部", "看多", "中性", "看空",
    ]);
  });

  it("shows a visible error and retries the catalog request", async () => {
    const catalog = vi.spyOn(api, "listCompanyNewsCatalog")
      .mockRejectedValueOnce(new Error("DA snapshot unavailable"))
      .mockResolvedValueOnce(page);
    const user = userEvent.setup();
    render(<CompanyNewsWorkbench report={report} busy={false} run={run} selectedSnapshot={[]} />);

    expect(await screen.findByText("DA snapshot unavailable")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("DA-Report headline")).toBeTruthy();
    expect(catalog).toHaveBeenCalledTimes(2);
  });
});
