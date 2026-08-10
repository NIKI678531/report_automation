import { describe, expect, it } from "vitest";
import {
  draftsFromSnapshot,
  FMP_SOURCE_FILTER,
  matchesNewsSource,
  providerFromSourceFilter,
  reportNewsWindow,
  shouldAutoLoadDaNews,
  toggleNewsSelection,
} from "./NewsWorkbench";
import type { NewsCandidate } from "../../api";

const ready = {
  activeSnapshotId: "snapshot-1",
  busy: false,
  candidateCount: 0,
  daConfigured: true,
  loading: false,
  readOnly: false,
  attempted: false,
};

describe("DA-Report automatic news loading", () => {
  it("loads once when a mutable report has a snapshot and no candidates", () => {
    expect(shouldAutoLoadDaNews(ready)).toBe(true);
    expect(shouldAutoLoadDaNews({ ...ready, attempted: true })).toBe(false);
  });

  it("does not load without a snapshot, provider, or empty candidate list", () => {
    expect(shouldAutoLoadDaNews({ ...ready, activeSnapshotId: null })).toBe(false);
    expect(shouldAutoLoadDaNews({ ...ready, daConfigured: false })).toBe(false);
    expect(shouldAutoLoadDaNews({ ...ready, candidateCount: 1 })).toBe(false);
    expect(shouldAutoLoadDaNews({ ...ready, readOnly: true })).toBe(false);
  });
});

describe("Company News report context", () => {
  it("uses the selected report month as the news window", () => {
    expect(reportNewsWindow("2026-08-31")).toEqual({ fromDate: "2026-08-01", toDate: "2026-08-31" });
  });

  it("shows a candidate in the selected-news model immediately after selection", () => {
    const candidate: NewsCandidate = {
      id: "news-1",
      source_name: "Reuters",
      source_url: "https://example.com/news-1",
      published_at: "2026-08-10T08:00:00Z",
      title: "Selected headline",
      summary: "Selected summary",
      security_code: "0700",
      ticker: "0700.HK",
      importance: "HIGH",
      match_confidence: 100,
      site: "example.com",
      provider: "DA_REPORT",
    };
    const selected = toggleNewsSelection([], candidate);
    expect(selected).toEqual([expect.objectContaining({ news_item_id: "news-1", title: "Selected headline" })]);
    expect(toggleNewsSelection(selected, candidate)).toEqual([]);
  });

  it("restores only the current report's saved selections", () => {
    expect(draftsFromSnapshot([], "2026-08-31")).toEqual([]);
    expect(draftsFromSnapshot([{ news_item_id: "news-2", title: "Saved", summary: "Summary" }], "2026-08-31"))
      .toEqual([expect.objectContaining({ news_item_id: "news-2", title: "Saved", publishedAt: "2026-08-31" })]);
  });
});

describe("Company News source filtering", () => {
  const fmpCandidate: NewsCandidate = {
    id: "news-fmp",
    source_name: "Reuters",
    source_url: "https://example.com/news-fmp",
    published_at: "2026-08-10T08:00:00Z",
    title: "FMP headline",
    summary: "FMP summary",
    security_code: "0700",
    ticker: "0700.HK",
    importance: "HIGH",
    match_confidence: 100,
    site: "example.com",
    provider: "FMP",
  };

  it("maps only the dedicated FMP option to a provider request", () => {
    expect(providerFromSourceFilter(FMP_SOURCE_FILTER)).toBe("FMP");
    expect(providerFromSourceFilter("Reuters")).toBeUndefined();
  });

  it("filters FMP by provider while preserving publisher filters", () => {
    expect(matchesNewsSource(fmpCandidate, FMP_SOURCE_FILTER)).toBe(true);
    expect(matchesNewsSource(fmpCandidate, "Reuters")).toBe(true);
    expect(matchesNewsSource(fmpCandidate, "")).toBe(true);
    expect(matchesNewsSource({ ...fmpCandidate, provider: "DA_REPORT", source_name: "FMP" }, FMP_SOURCE_FILTER)).toBe(false);
  });
});
