// @vitest-environment jsdom

import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "../../i18n";
import { RichTypographyEditor } from "./RichTypographyEditor";
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

function Harness({ onChange }: { onChange: (value: string) => void }) {
  const [value, setValue] = useState("<p>Key driver<br>Wrapped supporting copy.</p>");
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
