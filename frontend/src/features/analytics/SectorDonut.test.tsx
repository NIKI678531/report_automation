// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { SectorDonut, sectorSlices } from "./SectorDonut";

afterEach(cleanup);

describe("SectorDonut", () => {
  it("preserves backend order and only normalizes geometry", () => {
    expect(sectorSlices([], { slices: [
      { code: "23", label: "Consumer", weight: "0.4", start_angle: "0", end_angle: "144", color_index: 3 },
      { code: "70", label: "Technology", weight: "0.6", start_angle: "144", end_angle: "360", color_index: 5 },
    ] })).toMatchObject([
      { code: "23", sector: "Consumer", share: 0.4, offset: 0, colorIndex: 3 },
      { code: "70", sector: "Technology", share: 0.6, offset: 0.4, colorIndex: 5 },
    ]);
  });

  it("renders an accessible multi-slice SVG with a text legend", () => {
    const { container } = render(<SectorDonut sectors={[
      { code: "70", sector: "Technology", weight: "0.6" },
      { code: "23", sector: "Consumer", weight: "0.4" },
    ]} />);

    expect(screen.getByRole("img", { name: /Index Sectors Breakdown/i })).toBeTruthy();
    expect(container.querySelectorAll(".sector-donut-slice")).toHaveLength(2);
    expect(screen.getByText("Technology")).toBeTruthy();
    expect(screen.getByText("60.0%")).toBeTruthy();
  });
});