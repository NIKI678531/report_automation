// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { SectorDonut, sectorSlices } from "./SectorDonut";

afterEach(cleanup);

const CHART = {
  alt_text: "Index sector breakdown: Consumer 40.0%, Technology 60.0%",
  series: [
    {
      code: "23",
      label: "Consumer",
      raw_value: "0.4",
      display_value: "40.0%",
      sort_order: 1,
      color_token: "industry.hsics.23",
      start_angle: "0",
      end_angle: "144",
    },
    {
      code: "70",
      label: "Technology",
      raw_value: "0.6",
      display_value: "60.0%",
      sort_order: 2,
      color_token: "industry.hsics.70",
      start_angle: "144",
      end_angle: "360",
    },
  ],
};

describe("SectorDonut", () => {
  it("preserves backend order and only normalizes geometry", () => {
    expect(sectorSlices(CHART)).toMatchObject([
      { code: "23", sector: "Consumer", displayValue: "40.0%", share: 0.4, offset: 0 },
      { code: "70", sector: "Technology", displayValue: "60.0%", share: 0.6, offset: 0.4 },
    ]);
  });

  it("binds colour to the industry, not to the position in the list", () => {
    const [consumer, technology] = sectorSlices(CHART);
    const reordered = sectorSlices({ series: [CHART.series[1], CHART.series[0]] });

    expect(consumer.colorClass).not.toEqual(technology.colorClass);
    expect(reordered.map((slice) => slice.colorClass)).toEqual([technology.colorClass, consumer.colorClass]);
  });

  it("renders nothing without a chart snapshot rather than recomputing one", () => {
    expect(sectorSlices(undefined)).toEqual([]);
    expect(sectorSlices({ series: [] })).toEqual([]);
  });

  it("renders an accessible multi-slice SVG that shows the backend display value", () => {
    const { container } = render(<SectorDonut chart={CHART} />);

    expect(screen.getByRole("img", { name: /Index Sectors Breakdown/i })).toBeTruthy();
    expect(container.querySelectorAll(".sector-donut-slice")).toHaveLength(2);
    expect(screen.getByText("Technology")).toBeTruthy();
    expect(screen.getByText("60.0%")).toBeTruthy();
  });
});
