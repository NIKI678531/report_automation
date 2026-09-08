// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api, type Report, type TranslationJob } from "../../api";
import { LocaleProvider } from "../../i18n";
import { TranslationStatus } from "./TranslationStatus";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const report = { id: "target", language_mode: "ZH_HANS", status: "EDITING", translation_enabled: true, translation_source_report_id: "source", latest_document: { version: 1, content: {} } } as Report;
const completed: TranslationJob = { id: "job", source_report_id: "source", target_report_id: "target", source_document_version: 1, target_document_version: 1, status: "SUCCEEDED", result_document_version: 2, preserved_fields: [], error: null, request_id: "test" };

function setup(automaticSource?: string) {
  const apply = vi.fn(async () => true);
  const prepare = vi.fn(async () => report);
  const onConsumed = vi.fn();
  const onBusyChange = vi.fn();
  render(<LocaleProvider locale="zh-Hans"><TranslationStatus report={report} automaticSource={automaticSource} apply={apply} prepare={prepare} onConsumed={onConsumed} onBusyChange={onBusyChange} /></LocaleProvider>);
  return { apply, prepare, onConsumed, onBusyChange };
}

it("automatically translates once and applies the resulting document", async () => {
  vi.spyOn(api, "getReport").mockResolvedValue({ ...report, id: "source", language_mode: "EN" });
  const submit = vi.spyOn(api, "translateReport").mockResolvedValue(completed);
  const { apply, onConsumed } = setup("source");
  expect(await screen.findByText("译文已更新")).toBeTruthy();
  await waitFor(() => expect(apply).toHaveBeenCalledTimes(1));
  expect(submit).toHaveBeenCalledTimes(1);
  expect(submit).toHaveBeenCalledWith("source", "target", 1, 1, "auto:source:1:1");
  expect(onConsumed).toHaveBeenCalledTimes(1);
});

it("resumes a queued job without creating a new translation", async () => {
  vi.spyOn(api, "latestTranslation").mockResolvedValue({ ...completed, status: "QUEUED", result_document_version: null });
  vi.spyOn(api, "getTranslationJob").mockResolvedValue({ ...completed, preserved_fields: ["sections.month_in_review.summary"] });
  const submit = vi.spyOn(api, "translateReport");
  const { apply } = setup();
  expect(await screen.findByText("正在翻译回顾")).toBeTruthy();
  expect(await screen.findByText("已保留人工改稿；源文变更待核对")).toBeTruthy();
  expect(submit).not.toHaveBeenCalled();
  await waitFor(() => expect(apply).toHaveBeenCalledTimes(1));
});

it("keeps the saved report on failure and offers an explicit retry", async () => {
  vi.spyOn(api, "latestTranslation").mockResolvedValue({ ...completed, status: "FAILED", error: { error_code: "TRANSLATION_PROVIDER_UNAVAILABLE" } });
  vi.spyOn(api, "getReport").mockImplementation(async id => ({ ...report, id, language_mode: id === "source" ? "EN" : "ZH_HANS" }));
  vi.spyOn(api, "syncLanguageVariant").mockResolvedValue(report);
  const submit = vi.spyOn(api, "translateReport").mockResolvedValue(completed);
  const { apply, prepare } = setup();
  expect(await screen.findByText(/译文未应用/)).toBeTruthy();
  expect(apply).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "同步译文" }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(prepare).toHaveBeenCalledTimes(1);
});