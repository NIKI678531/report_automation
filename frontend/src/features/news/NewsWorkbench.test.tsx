import { describe, expect, it } from "vitest";
import {
  draftsFromSnapshot,
  matchesNewsSource,
  publishedDateHkt,
  reportNewsWindow,
  shouldAutoLoadDaNews,
  toggleNewsSelection,
} from "./NewsWorkbench";
import type { NewsCandidate } from "../../api";

const ready = {
  busy: false,
  candidateCount: 0,
  daConfigured: true,
  loading: false,
  readOnly: false,
  attempted: false,
};

describe("DA-Report automatic news loading", () => {
  it("loads once when a mutable report has no candidates", () => {
    expect(shouldAutoLoadDaNews(ready)).toBe(true);
    expect(shouldAutoLoadDaNews({ ...ready, attempted: true })).toBe(false);
  });

  it("does not load without a provider and re-ensures when a snapshot changes", () => {
    expect(shouldAutoLoadDaNews({ ...ready, daConfigured: false })).toBe(false);
    expect(shouldAutoLoadDaNews({ ...ready, candidateCount: 1 })).toBe(true);
    expect(shouldAutoLoadDaNews({ ...ready, readOnly: true })).toBe(false);
  });
});

describe("Company News report context", () => {
  it("uses the selected report month as the news window", () => {
    expect(reportNewsWindow("2026-08-31")).toEqual({ fromDate: "2026-08-01", toDate: "2026-08-31" });
  });

  it("uses the HKT publication date across a UTC month boundary", () => {
    expect(publishedDateHkt("2026-05-31T16:30:00Z")).toBe("2026-06-01");
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
  const candidate: NewsCandidate = {
    id: "news-da",
    source_name: "Reuters",
    source_url: "https://example.com/news-da",
    published_at: "2026-08-10T08:00:00Z",
    title: "DA-Report headline",
    summary: "DA-Report summary",
    security_code: "0700",
    ticker: "0700.HK",
    importance: "HIGH",
    match_confidence: 100,
    site: "example.com",
    provider: "DA_REPORT",
  };

  it("filters by publisher only", () => {
    expect(matchesNewsSource(candidate, "")).toBe(true);
    expect(matchesNewsSource(candidate, "Reuters")).toBe(true);
    expect(matchesNewsSource(candidate, "Bloomberg")).toBe(false);
  });
});
