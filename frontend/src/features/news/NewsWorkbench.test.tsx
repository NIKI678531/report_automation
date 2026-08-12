// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CompanyNewsWorkbench,
  catalogSelectionKey,
  draftsFromSnapshot,
  mergeCatalogItems,
  publishedDateHkt,
  toggleCatalogSelection,
} from "./CompanyNewsWorkbench";
import { api, type CompanyNewsCatalogItem, type Report } from "../../api";

const candidate: CompanyNewsCatalogItem = {
  provider: "DA_REPORT",
  external_id: "42",
  source_name: "Reuters",
  source_name_zh: "路透",
  source_code: "reuters",
  source_url: "https://example.com/news-42",
  published_at: "2026-08-10T08:00:00Z",
  published_at_source: "published_at",
  fetched_at: "2026-08-10T09:00:00Z",
  title: "DA-Report headline",
  title_en: "DA-Report headline",
  title_zh: "DA-Report 標題",
  summary: "DA-Report summary",
  summary_en: "DA-Report summary",
  summary_zh: "DA-Report 摘要",
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
  report_date: "2026-06-30",
  status: "DRAFT",
  lane: "PRODUCTION",
  revision: 1,
  version: 1,
  active_snapshot_id: null,
  finalized_document_version: null,
  latest_document: { version: 1, checksum: "checksum", content: { sections: { company_news: [] } } },
};

const page = {
  items: [candidate],
  total: 1,
  has_more: false,
  next_cursor: null,
  facets: {
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
    expect(catalog).toHaveBeenCalledWith("report-1", expect.objectContaining({ limit: 50, sort: "newest" }));
    await user.type(screen.getByLabelText("Search company news"), "Tencent");
    await waitFor(() => expect(catalog).toHaveBeenLastCalledWith(
      "report-1",
      expect.objectContaining({ query: "Tencent" }),
    ));
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
