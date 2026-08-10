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

  it("requests constituent news from FMP for the selected date window", async () => {
    const payload = { provider: "FMP", fetched: 0, created: 0, items: [] };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 }));
    await api.fetchNewsCandidates("r1", "CONSTITUENTS", "2026-08-01", "2026-08-10", "FMP");
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/reports/r1/news/candidates/fetch", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        scope: "CONSTITUENTS",
        from_date: "2026-08-01",
        to_date: "2026-08-10",
        page: 0,
        limit: 100,
        provider: "FMP",
        ensure: false,
      }),
    }));
    fetchMock.mockRestore();
  });
});
