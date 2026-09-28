// @vitest-environment jsdom

import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ReviewCanvas,
  historicalFootnoteParagraphs,
  markPreviewOverflows,
  pageOnePresentation,
  retargetHistoricalFootnoteStyles,
  type PageOnePresentation,
  type ReviewBlock,
} from "./ReviewCanvas";

const blocks: ReviewBlock[] = [
  {
    block_id: "summary",
    type: "rich_text",
    title: "June in Review",
    content: "<p>Monthly summary.</p>",
    x: 0,
    y: 0,
    w: 6,
    h: 2,
    text_align: "left",
  },
  {
    block_id: "drivers",
    type: "key_drivers",
    title: "Key Drivers",
    content: "<p>Driver.</p>",
    x: 6,
    y: 0,
    w: 6,
    h: 2,
    text_align: "left",
  },
];

function props(
  presentation: PageOnePresentation = pageOnePresentation(undefined, blocks),
  onPresentationChange: (next: PageOnePresentation) => void = vi.fn(),
) {
  return {
    blocks,
    presentation,
    historicalFootnote: "First paragraph.\n\nSecond paragraph.",
    historicalTitle: "Historical Performance of 3033.HK and Hang Seng TECH Index*",
    disabled: false,
    previewHtml: "",
    previewBusy: false,
    previewError: "",
    onBlocksChange: vi.fn(),
    onPresentationChange,
    onHistoricalFootnoteChange: vi.fn(),
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Review page-one layout controls", () => {
  it("counts only substantive footnote paragraphs", () => {
    expect(historicalFootnoteParagraphs("\n\nFirst\n\n\nSecond\n\n")).toEqual(["First", "Second"]);
    expect(historicalFootnoteParagraphs("\n\n")).toEqual([""]);
  });

  it("drops paragraph styles that no longer have target footnote text", () => {
    const presentation = pageOnePresentation(undefined, blocks);
    presentation.page_one.elements = presentation.page_one.elements.map((element) => (
      element.id === "footnote:historical"
        ? {
          ...element,
          paragraph_styles: [
            { paragraph_index: 0, font_size_role: "footnote-9", line_height_role: "1.2", text_align: "left" },
            { paragraph_index: 1, font_size_role: "footnote-10", line_height_role: "1.4", text_align: "right" },
          ],
        }
        : element
    ));

    const retargeted = retargetHistoricalFootnoteStyles(presentation, "Only one paragraph.");

    expect(retargeted.page_one.elements.find((element) => element.id === "footnote:historical")?.paragraph_styles).toEqual([
      { paragraph_index: 0, font_size_role: "footnote-9", line_height_role: "1.2", text_align: "left" },
    ]);
  });

  it("marks horizontal bounds and nested scroll overflow in the paged preview", () => {
    const previewDocument = document.implementation.createHTMLDocument("preview");
    previewDocument.body.innerHTML = `
      <section class="report-page" data-page="1">
        <main class="page-body">
          <section data-layout-id="review:safe">Safe</section>
          <section data-layout-id="review:wide"><span>Unbroken content</span></section>
          <section data-layout-id="review:overlap-a">Overlap A</section>
          <section data-layout-id="review:overlap-b">Overlap B</section>
          <section data-layout-id="historical_performance">Outside</section>
        </main>
        <div class="footnote" data-layout-id="footnote:historical">Footnote</div>
        <footer class="page-footer"></footer>
      </section>`;
    const page = previewDocument.querySelector<HTMLElement>(".report-page")!;
    const body = previewDocument.querySelector<HTMLElement>(".page-body")!;
    const footer = previewDocument.querySelector<HTMLElement>(".page-footer")!;
    const footnote = previewDocument.querySelector<HTMLElement>('[data-layout-id="footnote:historical"]')!;
    const safe = previewDocument.querySelector<HTMLElement>('[data-layout-id="review:safe"]')!;
    const wide = previewDocument.querySelector<HTMLElement>('[data-layout-id="review:wide"]')!;
    const wideContent = wide.querySelector<HTMLElement>("span")!;
    const overlapA = previewDocument.querySelector<HTMLElement>('[data-layout-id="review:overlap-a"]')!;
    const overlapB = previewDocument.querySelector<HTMLElement>('[data-layout-id="review:overlap-b"]')!;
    const outside = previewDocument.querySelector<HTMLElement>('[data-layout-id="historical_performance"]')!;
    const rect = (left: number, top: number, right: number, bottom: number): DOMRect => ({
      left, top, right, bottom, width: right - left, height: bottom - top,
      x: left, y: top, toJSON: () => ({}),
    });
    vi.spyOn(page, "getBoundingClientRect").mockReturnValue(rect(0, 0, 210, 297));
    vi.spyOn(body, "getBoundingClientRect").mockReturnValue(rect(10, 10, 200, 270));
    vi.spyOn(footer, "getBoundingClientRect").mockReturnValue(rect(10, 280, 200, 292));
    vi.spyOn(footnote, "getBoundingClientRect").mockReturnValue(rect(10, 255, 200, 265));
    vi.spyOn(safe, "getBoundingClientRect").mockReturnValue(rect(10, 20, 190, 40));
    vi.spyOn(wide, "getBoundingClientRect").mockReturnValue(rect(10, 50, 190, 70));
    vi.spyOn(overlapA, "getBoundingClientRect").mockReturnValue(rect(10, 110, 110, 140));
    vi.spyOn(overlapB, "getBoundingClientRect").mockReturnValue(rect(80, 130, 190, 160));
    vi.spyOn(outside, "getBoundingClientRect").mockReturnValue(rect(10, 80, 205, 100));
    Object.defineProperties(wideContent, {
      clientWidth: { configurable: true, value: 100 },
      scrollWidth: { configurable: true, value: 140 },
    });

    markPreviewOverflows(previewDocument);

    expect(safe.hasAttribute("data-layout-overflow")).toBe(false);
    expect(wide.getAttribute("data-layout-overflow")).toBe("true");
    expect(overlapA.getAttribute("data-layout-overflow")).toBe("true");
    expect(overlapB.getAttribute("data-layout-overflow")).toBe("true");
    expect(outside.getAttribute("data-layout-overflow")).toBe("true");
    expect(footnote.hasAttribute("data-layout-overflow")).toBe(false);
  });

  it("reflows provisional fixed elements when legacy presentation has no Review geometry", () => {
    const presentation = pageOnePresentation({
      schema_version: 1,
      page_one: {
        elements: [
          { id: "historical_performance", row: 0, row_span: 1, x: 0, w: 12, vertical_nudge_steps: 2 },
          { id: "footnote:historical", row: 1, row_span: 1, x: 0, w: 12, vertical_nudge_steps: 0, bottom_nudge_steps: 1, paragraph_styles: [] },
        ],
      },
    }, blocks);

    expect(presentation.page_one.elements.find((element) => element.id === "historical_performance")).toMatchObject({ row: 2, vertical_nudge_steps: 2 });
    expect(presentation.page_one.elements.find((element) => element.id === "footnote:historical")).toMatchObject({ row: 3, bottom_nudge_steps: 1 });
  });

  it("defaults and normalizes Historical Performance table style roles", () => {
    const defaultPresentation = pageOnePresentation(undefined, blocks);
    expect(defaultPresentation.page_one.elements.find((element) => element.id === "historical_performance")).toMatchObject({
      table_font_size_role: "history-10",
      table_line_height_role: "1.2",
    });

    const normalized = pageOnePresentation({
      schema_version: 1,
      page_one: {
        elements: [{
          id: "historical_performance",
          row: 2,
          row_span: 1,
          x: 0,
          w: 12,
          vertical_nudge_steps: 0,
          table_font_size_role: "history-11",
          table_line_height_role: "1.4",
        }],
      },
    }, blocks);
    expect(normalized.page_one.elements.find((element) => element.id === "historical_performance")).toMatchObject({
      table_font_size_role: "history-11",
      table_line_height_role: "1.4",
    });
  });

  it("keeps horizontal movement bounded while allowing a default block to move upward", () => {
    const onPresentationChange = vi.fn();
    const { container } = render(<ReviewCanvas {...props(undefined, onPresentationChange)} />);
    const controls = screen.getByLabelText("Page-one layout controls");

    expect(within(controls).getByRole("button", { name: "Move left one column" })).toHaveProperty("disabled", true);
    expect(within(controls).getByRole("button", { name: "Move right one column" })).toHaveProperty("disabled", true);
    expect(within(controls).getByRole("button", { name: "Reduce spacing by half a line" })).toHaveProperty("disabled", false);
    expect(within(controls).getByRole("button", { name: "Increase spacing by half a line" })).toHaveProperty("disabled", false);

    fireEvent.keyDown(container.querySelector(".page-one-editor") as HTMLElement, { key: "ArrowRight" });
    expect(onPresentationChange).not.toHaveBeenCalled();

    fireEvent.click(within(controls).getByRole("button", { name: "Reduce spacing by half a line" }));
    let updated = onPresentationChange.mock.calls[0][0] as PageOnePresentation;
    expect(updated.page_one.elements.find((element) => element.id === "review:summary")?.vertical_nudge_steps).toBe(-1);

    onPresentationChange.mockClear();
    fireEvent.click(within(controls).getByRole("button", { name: "Increase spacing by half a line" }));
    updated = onPresentationChange.mock.calls[0][0] as PageOnePresentation;
    expect(updated.page_one.elements.find((element) => element.id === "review:summary")?.vertical_nudge_steps).toBe(1);
  });

  it("moves a selected block with an arrow key but leaves arrows inside an input untouched", () => {
    const onPresentationChange = vi.fn();
    const presentation = pageOnePresentation(undefined, blocks);
    presentation.page_one.elements = presentation.page_one.elements.map((element) => (
      element.id === "review:summary" ? { ...element, x: 1, w: 4 } : element.id === "review:drivers" ? { ...element, x: 8, w: 4 } : element
    ));
    const { container } = render(<ReviewCanvas {...props(presentation, onPresentationChange)} />);

    fireEvent.keyDown(container.querySelector(".page-one-editor") as HTMLElement, { key: "ArrowLeft" });
    const updated = onPresentationChange.mock.calls[0][0] as PageOnePresentation;
    expect(updated.page_one.elements.find((element) => element.id === "review:summary")?.x).toBe(0);

    onPresentationChange.mockClear();
    const textarea = screen.getByRole("textbox", { name: "Historical performance footnote" });
    const inputArrow = new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true });
    textarea.dispatchEvent(inputArrow);
    expect(inputArrow.defaultPrevented).toBe(false);
    expect(onPresentationChange).not.toHaveBeenCalled();
  });

  it("stores font size, line spacing, and alignment for the selected footnote paragraph", () => {
    const onPresentationChange = vi.fn();
    const initial = pageOnePresentation(undefined, blocks);
    initial.page_one.elements = initial.page_one.elements.map((element) => element.id === "footnote:historical" ? {
      ...element,
      paragraph_styles: [{ paragraph_index: 0, font_size_role: "footnote-9", line_height_role: "1.0", text_align: "left" }],
    } : element);

    function StatefulCanvas() {
      const [presentation, setPresentation] = useState(initial);
      return <ReviewCanvas
        {...props(presentation, (next) => {
          onPresentationChange(next);
          setPresentation(next);
        })}
      />;
    }

    const { container } = render(<StatefulCanvas />);
    const footnoteEditor = container.querySelector(".historical-footnote-editor") as HTMLElement;
    fireEvent.change(within(footnoteEditor).getByLabelText("Paragraph"), { target: { value: "1" } });
    fireEvent.change(within(footnoteEditor).getByLabelText("Font size"), { target: { value: "footnote-10" } });
    fireEvent.change(within(footnoteEditor).getByLabelText("Line spacing"), { target: { value: "1.4" } });
    fireEvent.change(within(footnoteEditor).getByLabelText("Alignment"), { target: { value: "justify" } });

    const updated = onPresentationChange.mock.calls.at(-1)?.[0] as PageOnePresentation;
    expect(updated.page_one.elements.find((element) => element.id === "footnote:historical")?.paragraph_styles).toEqual([
      { paragraph_index: 0, font_size_role: "footnote-9", line_height_role: "1.0", text_align: "left" },
      { paragraph_index: 1, font_size_role: "footnote-10", line_height_role: "1.4", text_align: "justify" },
    ]);
  });

  it("stores editable font size and line spacing for the read-only Historical Performance table", () => {
    const onPresentationChange = vi.fn();
    const initial = pageOnePresentation(undefined, blocks);

    function StatefulCanvas() {
      const [presentation, setPresentation] = useState(initial);
      return <ReviewCanvas
        {...props(presentation, (next) => {
          onPresentationChange(next);
          setPresentation(next);
        })}
      />;
    }

    render(<StatefulCanvas />);
    fireEvent.change(screen.getByLabelText("Historical table font size"), { target: { value: "history-11" } });
    fireEvent.change(screen.getByLabelText("Historical table line spacing"), { target: { value: "1.4" } });

    const updated = onPresentationChange.mock.calls.at(-1)?.[0] as PageOnePresentation;
    expect(updated.page_one.elements.find((element) => element.id === "historical_performance")).toMatchObject({
      table_font_size_role: "history-11",
      table_line_height_role: "1.4",
    });
    expect(screen.getByText("Values are read-only")).toBeTruthy();
  });

  it("applies alignment only to the active Review paragraph", async () => {
    Object.defineProperties(window.Range.prototype, {
      getClientRects: { configurable: true, value: () => [] },
      getBoundingClientRect: {
        configurable: true,
        value: () => ({ left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}) }),
      },
    });
    const onBlocksChange = vi.fn();
    const twoParagraphBlocks = [{
      ...blocks[0],
      content: "<p>First paragraph.</p><p>Second paragraph.</p>",
      text_align: "left" as const,
    }];
    const presentation = pageOnePresentation(undefined, twoParagraphBlocks);
    render(<ReviewCanvas
      {...props(presentation)}
      blocks={twoParagraphBlocks}
      onBlocksChange={onBlocksChange}
    />);

    fireEvent.click(screen.getByTitle("Align center"));

    await waitFor(() => expect(onBlocksChange).toHaveBeenCalled());
    const updated = onBlocksChange.mock.calls.at(-1)?.[0] as ReviewBlock[];
    expect(updated[0].text_align).toBe("left");
    expect(updated[0].content).toContain('data-text-align="center"');
    expect(updated[0].content.match(/data-text-align=/g)).toHaveLength(1);
  });

  it("selects a layout element by clicking it in the paged preview", () => {
    const previewHtml = '<html><body><section data-layout-id="footnote:historical">Footnote</section></body></html>';
    const { container } = render(<ReviewCanvas {...props()} previewHtml={previewHtml} />);
    const iframe = screen.getByTitle("Live paged preview") as HTMLIFrameElement;
    const iframeDocument = iframe.contentDocument;
    expect(iframeDocument).not.toBeNull();
    iframeDocument!.body.innerHTML = '<section data-layout-id="footnote:historical">Footnote</section>';
    fireEvent.load(iframe);
    fireEvent.click(iframeDocument!.querySelector("[data-layout-id='footnote:historical']") as Element);

    const controls = screen.getByLabelText("Page-one layout controls");
    expect(within(controls).getByText("Historical performance footnote")).toBeTruthy();
    expect(container.querySelector(".historical-footnote-editor")?.className).toContain("selected");
  });

  it("renders only page one at fixed A4 geometry and rescales its iframe height with the pane", async () => {
    const previewHtml = `<!doctype html><html><head></head><body><article class="report-document">
      <section class="report-page" data-page="1"><main class="page-body"><section data-layout-id="review:summary">Review</section><section data-layout-id="historical_performance">History</section></main><div class="footnote" data-layout-id="footnote:historical">Footnote</div><footer class="page-footer"></footer></section>
      <section class="report-page" data-page="2">Company News</section>
    </article></body></html>`;
    render(<ReviewCanvas {...props()} previewHtml={previewHtml} />);
    const iframe = screen.getByTitle("Live paged preview") as HTMLIFrameElement;

    expect(iframe.getAttribute("srcdoc")).toContain('data-page="1"');
    expect(iframe.getAttribute("srcdoc")).not.toContain('data-page="2"');

    const iframeDocument = iframe.contentDocument!;
    iframeDocument.body.innerHTML = previewHtml;
    const page = iframeDocument.querySelector<HTMLElement>('[data-page="1"]')!;
    vi.spyOn(page, "getBoundingClientRect").mockReturnValue({
      left: 0, top: 0, right: 800, bottom: 1200, width: 800, height: 1200,
      x: 0, y: 0, toJSON: () => ({}),
    });
    let paneWidth = 400;
    Object.defineProperty(iframe, "clientWidth", { configurable: true, get: () => paneWidth });

    fireEvent.load(iframe);

    await waitFor(() => expect(page.style.getPropertyValue("--review-preview-scale")).toBe("0.5"));
    expect(iframeDocument.querySelector('[data-page="2"]')).toBeNull();
    expect(iframeDocument.querySelector("style[data-review-preview]")?.textContent).toContain("width: 210mm !important");
    expect(iframeDocument.querySelector("style[data-review-preview]")?.textContent).toContain("height: 297mm !important");
    expect(iframe.style.height).toBe("600px");

    paneWidth = 200;
    fireEvent(window, new Event("resize"));
    await waitFor(() => expect(page.style.getPropertyValue("--review-preview-scale")).toBe("0.25"));
    expect(iframe.style.height).toBe("300px");
  });

  it("collapses and expands the desktop preview without removing its mobile content", () => {
    const { container } = render(<ReviewCanvas {...props()} previewHtml={'<html><body><section class="report-page" data-page="1">Review</section></body></html>'} />);
    const collapse = screen.getByRole("button", { name: "Collapse live preview" });
    const contentId = collapse.getAttribute("aria-controls")!;

    expect(collapse.getAttribute("aria-expanded")).toBe("true");
    expect(document.getElementById(contentId)?.hasAttribute("hidden")).toBe(false);
    fireEvent.click(collapse);

    const expand = screen.getByRole("button", { name: "Expand live preview" });
    expect(expand.getAttribute("aria-expanded")).toBe("false");
    expect(container.querySelector(".page-one-editor-grid")?.className).toContain("preview-collapsed");
    expect(document.getElementById(contentId)?.querySelector("iframe")).not.toBeNull();
  });
});
