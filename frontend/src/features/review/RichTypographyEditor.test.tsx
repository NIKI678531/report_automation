// @vitest-environment jsdom

import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "../../i18n";
import { normalizeRichHtmlForSubmission, RichTypographyEditor } from "./RichTypographyEditor";
import type { TextStyle } from "./reviewPresentation";

const defaultStyle: TextStyle = {
  font_family: "Calibri",
  font_size_pt: 10,
  color: "#000000",
  bold: false,
  italic: false,
  underline: false,
  line_height: 1.2,
  space_before_pt: 0,
  space_after_pt: 0,
  text_align: "left",
};

afterEach(cleanup);

function Harness({ onChange, initialValue = "<p>Key driver<br>Wrapped supporting copy.</p>" }: { onChange: (value: string) => void; initialValue?: string }) {
  const [value, setValue] = useState(initialValue);
  return <LocaleProvider locale="en">
    <RichTypographyEditor
      label="Review body"
      value={value}
      defaultStyle={defaultStyle}
      disabled={false}
      onChange={(next) => {
        onChange(next);
        setValue(next);
      }}
      onDefaultStyleChange={vi.fn()}
    />
  </LocaleProvider>;
}

describe("RichTypographyEditor paragraph structure", () => {
  it("removes pasted link and formatting attributes that the API does not support", () => {
    const normalized = normalizeRichHtmlForSubmission(`
      <div class="source-copy">
        <p style="font-size: 18px" onclick="alert(1)" data-text-align="center">
          Visit <a href="https://example.com/report" target="_blank" rel="noopener" title="Report">the report</a>
          or <a href="tel:+85212345678" target="_blank">call us</a>.
        </p>
        <ol start="4"><li style="color: red">Fourth point</li></ol>
      </div>
    `);

    expect(normalized).toContain('<p data-text-align="center">');
    expect(normalized).toContain('<a href="https://example.com/report">the report</a>');
    expect(normalized).toContain("<a>call us</a>");
    expect(normalized).toContain("<ol><li>Fourth point</li></ol>");
    expect(normalized).not.toMatch(/\b(?:class|onclick|rel|start|style|target|title)=/);
  });

  it("does not turn URL-like plain text into a link when it is pasted", async () => {
    const onChange = vi.fn();
    const { container } = render(<Harness onChange={onChange} initialValue="<p></p>" />);
    const editable = container.querySelector<HTMLElement>('[contenteditable="true"]')!;

    fireEvent.paste(editable, {
      clipboardData: {
        types: ["text/plain"],
        getData: (type: string) => type === "text/plain" ? "Ticker ABC.com is plain text." : "",
      },
    });

    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const html = String(onChange.mock.calls.at(-1)?.[0]);
    expect(html).toContain("ABC.com");
    expect(html).not.toContain("<a");
  });

  it("creates a numbered list and applies reversible whole-paragraph indentation", async () => {
    Object.defineProperties(window.Range.prototype, {
      getClientRects: { configurable: true, value: () => [] },
      getBoundingClientRect: {
        configurable: true,
        value: () => ({
          left: 0, top: 0, right: 0, bottom: 0,
          width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}),
        }),
      },
    });
    const onChange = vi.fn();
    const { container } = render(<Harness onChange={onChange} />);

    fireEvent.click(screen.getByTitle("Numbered list"));
    await waitFor(() => expect(container.querySelector("ol > li")).not.toBeNull());
    expect(screen.getByTitle("Numbered list").getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(screen.getByTitle("Increase paragraph indent"));
    await waitFor(() => {
      expect(container.querySelector("ol > li")?.getAttribute("data-indent-level")).toBe("1");
    });

    fireEvent.click(screen.getByTitle("Decrease paragraph indent"));
    await waitFor(() => {
      expect(container.querySelector("ol > li")?.hasAttribute("data-indent-level")).toBe(false);
    });
    expect(onChange).toHaveBeenCalled();
  });
});
