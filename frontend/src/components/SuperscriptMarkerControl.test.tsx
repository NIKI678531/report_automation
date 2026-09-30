// @vitest-environment jsdom

import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import {
  MarkerInput,
  MarkerTextarea,
  insertMarkerAtSelection,
  normalizeSuperscriptMarker,
} from "./SuperscriptMarkerControl";

afterEach(cleanup);

describe("superscript footnote markers", () => {
  it("normalizes editable digit markers and preserves common publication symbols", () => {
    expect(normalizeSuperscriptMarker("120")).toBe("¹²⁰");
    expect(normalizeSuperscriptMarker("⁴†‡*")).toBe("⁴†‡*");
    expect(normalizeSuperscriptMarker("1a")).toBeNull();
    expect(normalizeSuperscriptMarker("")).toBeNull();
  });

  it("inserts before or after selected text without replacing the selection", () => {
    expect(insertMarkerAtSelection("Wind,", 0, 4, "¹", "before")).toEqual({
      value: "¹Wind,",
      selectionStart: 1,
      selectionEnd: 5,
    });
    expect(insertMarkerAtSelection("Wind,", 0, 4, "¹", "after")).toEqual({
      value: "Wind¹,",
      selectionStart: 0,
      selectionEnd: 4,
    });
  });

  it("returns focus and the shifted selection to a textarea after insertion", async () => {
    function Harness() {
      const [value, setValue] = useState("Wind,");
      return <MarkerTextarea aria-label="Narrative" value={value} onValueChange={setValue} />;
    }

    render(<Harness />);
    const textarea = screen.getByRole("textbox", { name: "Narrative" }) as HTMLTextAreaElement;
    textarea.focus();
    textarea.setSelectionRange(0, 4);
    fireEvent.select(textarea);

    const markerControls = screen.getByRole("group", { name: "Superscript footnote marker" });
    fireEvent.click(within(markerControls).getByRole("button", { name: "Insert before selection" }));

    await waitFor(() => {
      expect(textarea.value).toBe("¹Wind,");
      expect(document.activeElement).toBe(textarea);
      expect([textarea.selectionStart, textarea.selectionEnd]).toEqual([1, 5]);
    });
  });

  it("supports the same insertion behavior in single-line editorial fields", async () => {
    function Harness() {
      const [value, setValue] = useState("Wind,");
      return <MarkerInput aria-label="Headline" value={value} onValueChange={setValue} />;
    }

    render(<Harness />);
    const input = screen.getByRole("textbox", { name: "Headline" }) as HTMLInputElement;
    input.focus();
    input.setSelectionRange(0, 4);
    fireEvent.select(input);
    const markerControls = screen.getByRole("group", { name: "Superscript footnote marker" });
    fireEvent.change(within(markerControls).getByRole("textbox", { name: "Marker" }), { target: { value: "2" } });
    fireEvent.click(within(markerControls).getByRole("button", { name: "Insert after selection" }));

    await waitFor(() => {
      expect(input.value).toBe("Wind²,");
      expect(document.activeElement).toBe(input);
      expect([input.selectionStart, input.selectionEnd]).toEqual([0, 4]);
    });
  });
});
