import { describe, expect, it } from "vitest";
import {
  REPORT_MODULES,
  reportMonthName,
  reportPageEyebrow,
  reportPageLabel,
  reportProductTicker,
  reportsForContext,
} from "./reportModules";

describe("report module page labels", () => {
  it("matches the four-page canonical report", () => {
    expect(REPORT_MODULES.map(({ pageLabel }) => pageLabel)).toEqual([
      "01",
      "01",
      "02",
      "03",
      "04",
      "01/03/04",
    ]);
    expect(reportPageLabel("performance")).toBe("01");
    expect(reportPageLabel("footnotes")).toBe("01/03/04");
    expect(reportPageEyebrow("analytics", "Calculated outputs")).toBe("Page 04 · Calculated outputs");
    expect(reportPageEyebrow("footnotes", "System-bound disclosures")).toBe("Pages 01/03/04 · System-bound disclosures");
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

  it("keeps report revisions inside the selected fund and report date", () => {
    const reports = [
      { id: "july-r2", product_code: "3033", report_date: "2026-07-31" },
      { id: "july-r1", product_code: "3033", report_date: "2026-07-31" },
      { id: "june", product_code: "3033", report_date: "2026-06-30" },
      { id: "other-fund", product_code: "9999", report_date: "2026-07-31" },
    ];
    expect(reportsForContext(reports, "3033", "2026-07-31").map(({ id }) => id)).toEqual(["july-r2", "july-r1"]);
  });
});