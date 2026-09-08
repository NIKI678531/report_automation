// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";

describe("FastAPI client", () => {
  it("creates reports through the versioned API", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ id: "r1" }), { status: 201 }));
    await api.createReport("2026-06-30", "3033");
    expect(fetchMock).toHaveBeenCalledWith("/remote/fund-cmt-auto/api/v1/reports", expect.objectContaining({ method: "POST", body: JSON.stringify({ product_code: "3033", report_date: "2026-06-30" }) }));
    fetchMock.mockRestore();
  });

  it("creates a language variant from a locked source document version", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ id: "zh1" }), { status: 201 }));
    await api.createLanguageVariant("en1", "ZH_HANS", 4);
    expect(fetchMock).toHaveBeenCalledWith("/remote/fund-cmt-auto/api/v1/reports/en1/language-variants", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ language_mode: "ZH_HANS", source_document_version: 4 }),
    }));
    fetchMock.mockRestore();
  });

  it("creates a Traditional Chinese language variant", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ id: "zh-hant-1" }), { status: 201 }));
    await api.createLanguageVariant("en1", "ZH_HANT", 4);
    expect(fetchMock).toHaveBeenCalledWith("/remote/fund-cmt-auto/api/v1/reports/en1/language-variants", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ language_mode: "ZH_HANT", source_document_version: 4 }),
    }));
    fetchMock.mockRestore();
  });

  it("sends the 3033 constituent company scope to the catalog API", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200 }));
    await api.listCompanyNewsCatalog("r1", { company_scope: "CONSTITUENTS" });
    expect(fetchMock).toHaveBeenCalledWith(
      "/remote/fund-cmt-auto/api/v1/reports/r1/news/catalog?company_scope=CONSTITUENTS",
      expect.any(Object),
    );
    fetchMock.mockRestore();
  });

  it("synchronizes module choices between language variants with optimistic locking", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ id: "zh1" }), { status: 200 }));
    await api.syncLanguageVariant("en1", "zh1", 4, 6);
    expect(fetchMock).toHaveBeenCalledWith("/remote/fund-cmt-auto/api/v1/reports/en1/language-variants/zh1/sync", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ source_document_version: 4, target_document_version: 6 }),
    }));
    fetchMock.mockRestore();
  });

  it("soft-deletes the selected report with optimistic locking", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));
    await api.deleteReport("r1", 7);
    expect(fetchMock).toHaveBeenCalledWith("/remote/fund-cmt-auto/api/v1/reports/r1?version=7", expect.objectContaining({ method: "DELETE" }));
    fetchMock.mockRestore();
  });

  it("loads the effective product catalog", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("[]", { status: 200 }));
    await api.listProducts("2026-06-30");
    expect(fetchMock).toHaveBeenCalledWith("/remote/fund-cmt-auto/api/v1/products?as_of_date=2026-06-30", expect.any(Object));
    fetchMock.mockRestore();
  });

  it("requests constituent news from the named provider for the selected date window", async () => {
    const payload = { provider: "DA_REPORT", fetched: 0, created: 0, items: [] };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 }));
    await api.fetchNewsCandidates("r1", "CONSTITUENTS", "2026-08-01", "2026-08-10", "DA_REPORT");
    expect(fetchMock).toHaveBeenCalledWith("/remote/fund-cmt-auto/api/v1/reports/r1/news/candidates/fetch", expect.objectContaining({
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

  it("queries the DA company news catalog with cursor-bound filters", async () => {
    const payload = { items: [], total: 0, has_more: false, next_cursor: null, facets: {} };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 }));
    await api.listCompanyNewsCatalog("r1", {
      query: "Tencent results",
      company: "700",
      sentiment: "bull",
      sort: "oldest",
      cursor: "next-page",
      limit: 25,
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/remote/fund-cmt-auto/api/v1/reports/r1/news/catalog?query=Tencent+results&company=700&sentiment=bull&sort=oldest&cursor=next-page&limit=25",
      expect.any(Object),
    );
    fetchMock.mockRestore();
  });

  it("saves DA catalog selections by trusted external id", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ version: 2, items: [] }), { status: 200 }));
    await api.selectNews("r1", 1, [{ provider: "DA_REPORT", external_id: "42", position: 0 }]);
    expect(fetchMock).toHaveBeenCalledWith("/remote/fund-cmt-auto/api/v1/reports/r1/news", expect.objectContaining({
      method: "PUT",
      body: JSON.stringify({ version: 1, items: [{ provider: "DA_REPORT", external_id: "42", position: 0 }] }),
    }));
    fetchMock.mockRestore();
  });

  it("applies first-time data without an override reason", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    await api.applyImport("r1", "i1");
    expect(fetchMock).toHaveBeenCalledWith("/remote/fund-cmt-auto/api/v1/reports/r1/imports/i1/apply", expect.objectContaining({
      method: "POST",
      body: "{}",
    }));
    fetchMock.mockRestore();
  });

  it("discards an unapplied import", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    await api.discardImport("r1", "i1");
    expect(fetchMock).toHaveBeenCalledWith("/remote/fund-cmt-auto/api/v1/reports/r1/imports/i1/discard", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({}),
    }));
    fetchMock.mockRestore();
  });

  it("clears an applied constituent dataset with optimistic locking", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    await api.clearDataset("r1", "constituent_returns", 7);
    expect(fetchMock).toHaveBeenCalledWith("/remote/fund-cmt-auto/api/v1/reports/r1/datasets/constituent_returns/clear", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ version: 7 }),
    }));
    fetchMock.mockRestore();
  });

  it("refreshes automatic data for the selected report version", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ changed: true, snapshot: {} }), { status: 200 }));
    await api.refreshAutomaticData("r1", 7);
    expect(fetchMock).toHaveBeenCalledWith("/remote/fund-cmt-auto/api/v1/reports/r1/automatic-data/refresh", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ version: 7 }),
    }));
    fetchMock.mockRestore();
  });

  it("sends a reason when replacing current data", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    await api.applyImport("r1", "i2", "Corrected source file");
    expect(fetchMock).toHaveBeenCalledWith("/remote/fund-cmt-auto/api/v1/reports/r1/imports/i2/apply", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ reason: "Corrected source file" }),
    }));
    fetchMock.mockRestore();
  });

  it("generates the requested format and downloads a blob through the remote path", async () => {
    const signed = "/api/v1/reports/r1/exports/pdf/content?version=1&expires=123&signature=a%2Bb";
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ download_url: signed })))
      .mockResolvedValueOnce(new Response("%PDF-test", { headers: { "Content-Type": "application/pdf", "Content-Disposition": 'attachment; filename="report.pdf"' } }));
    const create = vi.fn(() => "blob:test-export");
    const revoke = vi.fn();
    const OriginalURL = globalThis.URL;
    class DownloadURL extends OriginalURL { static createObjectURL = create; static revokeObjectURL = revoke; }
    vi.stubGlobal("URL", DownloadURL);
    vi.useFakeTimers();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe("report.pdf");
      expect(this.href).toBe("blob:test-export");
    });
    try {
      await api.downloadReport("r1", "pdf");
      expect(fetchMock).toHaveBeenNthCalledWith(1, "/remote/fund-cmt-auto/api/v1/reports/r1/exports/pdf/download", expect.any(Object));
      expect(fetchMock).toHaveBeenNthCalledWith(2, `/remote/fund-cmt-auto${signed}`, expect.any(Object));
      expect(click).toHaveBeenCalledOnce();
      expect(document.querySelector('a[download]')).toBeNull();
      vi.runAllTimers();
      expect(revoke).toHaveBeenCalledWith("blob:test-export");
    } finally {
      vi.useRealTimers();
      click.mockRestore();
      fetchMock.mockRestore();
      vi.unstubAllGlobals();
    }
  });

  it("surfaces generation failure instead of navigating to an error response", async () => {
    const signed = "/api/v1/reports/r1/exports/pdf/content?version=1&expires=123&signature=x";
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ download_url: signed })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ error_code: "EXPORT_FAILED", message: "Export failed", fix_hint: "Retry." }), { status: 503 }));
    try {
      await expect(api.downloadReport("r1", "pdf")).rejects.toMatchObject({ errorCode: "EXPORT_FAILED", message: "Export failed Retry." });
    } finally { fetchMock.mockRestore(); }
  });

});

describe("failed requests", () => {
  function respondWith(body: BodyInit | null, init: ResponseInit) {
    return vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(body, init));
  }

  /** The rejection, or a failure if the call unexpectedly succeeded — a resolved promise is a bug too. */
  async function failureOf(call: Promise<unknown>): Promise<ApiError> {
    try {
      await call;
    } catch (caught) {
      return caught as ApiError;
    }
    throw new Error("Expected the request to reject, but it resolved.");
  }

  it("shows the message and the fix hint instead of raw JSON", async () => {
    const fetchMock = respondWith(JSON.stringify({
      error_code: "FILE_TOO_LARGE",
      message: "The upload exceeds the 20 MB limit for this endpoint.",
      severity: "BLOCKING",
      fix_hint: "Split the file, or export only the rows for the reporting period.",
      request_id: "req-1",
    }), { status: 413 });

    const failure = await failureOf(api.listReports());

    expect(failure).toBeInstanceOf(ApiError);
    expect(failure.status).toBe(413);
    expect(failure.errorCode).toBe("FILE_TOO_LARGE");
    expect(failure.requestId).toBe("req-1");
    // Call sites use String(caught); it must read as a sentence, not as a serialized envelope.
    expect(String(failure)).toBe(
      "The upload exceeds the 20 MB limit for this endpoint. Split the file, or export only the rows for the reporting period.",
    );
    expect(String(failure)).not.toContain("error_code");
    fetchMock.mockRestore();
  });

  it("names the offending fields from a validation envelope", async () => {
    const fetchMock = respondWith(JSON.stringify({
      error_code: "REQUEST_INVALID",
      message: "The request body or query string failed schema validation.",
      fix_hint: "",
      findings: [{ error_code: "REQUEST_FIELD_INVALID", field: "body.source_url", message: "Value error, source_url must be an http:// or https:// address." }],
    }), { status: 422 });

    const failure = await failureOf(api.listReports());

    expect(failure.findings).toHaveLength(1);
    expect(String(failure)).toContain("body.source_url");
    fetchMock.mockRestore();
  });

  it("falls back to a readable message when the proxy answers instead of the API", async () => {
    // nginx returns an HTML error page, which must never be rendered into the status rail.
    const fetchMock = respondWith("<html><body><h1>502 Bad Gateway</h1></body></html>", {
      status: 502,
      headers: { "Content-Type": "text/html" },
    });

    const failure = await failureOf(api.listReports());

    expect(failure.status).toBe(502);
    expect(String(failure)).not.toContain("<html>");
    expect(String(failure)).toContain("did not respond");
    fetchMock.mockRestore();
  });

  it("stays an Error so existing catch blocks keep working", async () => {
    const fetchMock = respondWith(null, { status: 403 });
    const failure = await failureOf(api.listReports());
    expect(failure).toBeInstanceOf(Error);
    fetchMock.mockRestore();
  });
});
