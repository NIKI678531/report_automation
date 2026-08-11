import { describe, expect, it, vi } from "vitest";
import { api } from "./api";

describe("FastAPI client", () => {
  it("creates reports through the versioned API", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ id: "r1" }), { status: 201 }));
    await api.createReport("2026-06-30", "3033");
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/reports", expect.objectContaining({ method: "POST", body: JSON.stringify({ product_code: "3033", report_date: "2026-06-30" }) }));
    fetchMock.mockRestore();
  });

  it("loads the effective product catalog", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("[]", { status: 200 }));
    await api.listProducts("2026-06-30");
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/products?as_of_date=2026-06-30", expect.any(Object));
    fetchMock.mockRestore();
  });

  it("requests constituent news from the named provider for the selected date window", async () => {
    const payload = { provider: "DA_REPORT", fetched: 0, created: 0, items: [] };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 }));
    await api.fetchNewsCandidates("r1", "CONSTITUENTS", "2026-08-01", "2026-08-10", "DA_REPORT");
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/reports/r1/news/candidates/fetch", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        scope: "CONSTITUENTS",
        from_date: "2026-08-01",
        to_date: "2026-08-10",
        page: 0,
        limit: 100,
        provider: "DA_REPORT",
        ensure: false,
      }),
    }));
    fetchMock.mockRestore();
  });

  it("applies first-time data without an override reason", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    await api.applyImport("r1", "i1");
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/reports/r1/imports/i1/apply", expect.objectContaining({
      method: "POST",
      body: "{}",
    }));
    fetchMock.mockRestore();
  });

  it("sends a reason when replacing current data", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    await api.applyImport("r1", "i2", "Corrected source file");
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/reports/r1/imports/i2/apply", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ reason: "Corrected source file" }),
    }));
    fetchMock.mockRestore();
  });

  it("requests all canonical output formats", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("[]", { status: 202 }));
    await api.render("r1");
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/reports/r1/renders", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ formats: ["html", "pdf", "docx"] }),
    }));
    fetchMock.mockRestore();
  });
});
