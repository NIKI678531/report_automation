import { describe, expect, it } from "vitest";
import {
  REPORT_MODULES,
  reportConstituentsTitle,
  reportMonthName,
  reportPageEyebrow,
  reportPageLabel,
  reportProductTicker,
  reportsForContext,
  selectInitialReport,
  selectReportForMonth,
} from "./reportModules";

describe("report module page labels", () => {
  it("uses a continuous workspace sequence", () => {
    expect(REPORT_MODULES.map(({ pageLabel }) => pageLabel)).toEqual([
      "01",
      "02",
      "03",
      "04",
      "05",
      "06",
    ]);
    expect(reportPageLabel("constituents")).toBe("04");
    expect(reportPageLabel("footnotes")).toBe("06");
    expect(reportPageEyebrow("constituents", "Snapshot data")).toBe("Page 04 · Snapshot data");
    expect(reportPageEyebrow("analytics", "Calculated outputs")).toBe("Page 05 · Calculated outputs");
    expect(reportPageEyebrow("footnotes", "Free layout")).toBe("Page 06 · Free layout");
  });

  it("prefers canonical document identity with safe legacy fallbacks", () => {
    const canonical = {
      product_code: "TEST",
      report_date: "2026-07-31",
      latest_document: { content: { month_name: "Custom month", product_ticker: "9999.HK" } },
    };
    expect(reportMonthName(canonical)).toBe("Custom month");
    expect(reportProductTicker(canonical)).toBe("9999.HK");
    expect(reportMonthName({ product_code: "TEST", report_date: "2026-07-31" })).toBe("July");
    expect(reportProductTicker({ product_code: "TEST", report_date: "2026-07-31" })).toBe("TEST");
  });

  it("builds the constituent heading from the selected fund index", () => {
    expect(reportConstituentsTitle({ constituent_index_code: "HSTECH" })).toBe("The Performance of HSTECH Constituents");
    expect(reportConstituentsTitle({ constituent_index_code: "MSCI CHINA" })).toBe("The Performance of MSCI CHINA Constituents");
  });

  it("keeps report revisions inside the selected fund and report date", () => {
    const reports = [
      { id: "july-r2", product_code: "3033", report_date: "2026-07-31" },
      { id: "july-r1", product_code: "3033", report_date: "2026-07-31" },
      { id: "june", product_code: "3033", report_date: "2026-06-30" },
      { id: "other-fund", product_code: "9999", report_date: "2026-07-31" },
    ];
    expect(reportsForContext(reports, "3033", "2026-07-31").map(({ id }) => id)).toEqual(["july-r2", "july-r1"]);
  });

  it("opens the latest production report instead of the oldest active snapshot", () => {
    const reports = [
      { id: "april", product_code: "3033", report_date: "2026-04-04", version: 3, lane: "PRODUCTION" },
      { id: "june-r5", product_code: "3033", report_date: "2026-06-30", version: 5, lane: "PRODUCTION" },
      { id: "june-r6", product_code: "3033", report_date: "2026-06-30", version: 6, lane: "PRODUCTION" },
      { id: "testing", product_code: "3033", report_date: "2026-07-31", version: 1, lane: "TESTING" },
    ];

    expect(selectInitialReport(reports, "3033")?.id).toBe("june-r6");
  });

  it("opens the newest non-archived production revision for a selected month", () => {
    const reports = [
      { id: "r1", product_code: "3033", report_date: "2025-12-31", revision: 1, version: 9, lane: "PRODUCTION", status: "FINALIZED" },
      { id: "r2", product_code: "3033", report_date: "2025-12-31", revision: 2, version: 1, lane: "PRODUCTION", status: "DRAFT" },
      { id: "archived", product_code: "3033", report_date: "2025-12-31", revision: 3, version: 1, lane: "PRODUCTION", status: "ARCHIVED" },
      { id: "testing", product_code: "3033", report_date: "2025-12-31", revision: 4, version: 1, lane: "TESTING", status: "DRAFT" },
    ];

    expect(selectReportForMonth(reports, "3033", "2025-12-31")?.id).toBe("r2");
  });
});
