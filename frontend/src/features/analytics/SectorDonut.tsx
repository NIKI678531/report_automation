interface SectorSeriesEntry {
  code: string;
  sector: string;
  displayValue: string;
  share: number;
  offset: number;
  colorClass: string;
}

export interface SectorChartSnapshot {
  series?: unknown;
  alt_text?: unknown;
}

/**
 * Product-UI colour classes, bound to the industry rather than to its position in the list.
 * The backend hands us a `color_token`; this maps it onto the design-system swatch classes in
 * `styles.css`. It is deliberately *not* the report output palette — report tokens
 * (`backend/app/rendering/tokens/`) and the product design system are separate contracts.
 */
const INDUSTRY_COLOR_CLASS: Record<string, number> = {
  "industry.hsics.23": 1,
  "industry.hsics.70": 2,
  "industry.hsics.28": 3,
  "industry.hsics.10": 4,
  "industry.hsics.50": 5,
};

/**
 * Read the `industry_breakdown` chart snapshot. Order, the zero-weight filter, the percentage
 * string and the colour identity are all decided by the backend; the browser only turns angles
 * into stroke geometry. It must never recompute a number that appears on screen.
 */
export function sectorSlices(chart?: SectorChartSnapshot): SectorSeriesEntry[] {
  if (!Array.isArray(chart?.series)) return [];
  return chart.series.flatMap((value, index) => {
    if (!value || typeof value !== "object") return [];
    const row = value as Record<string, unknown>;
    const startAngle = Number(row.start_angle);
    const endAngle = Number(row.end_angle);
    if (!Number.isFinite(startAngle) || !Number.isFinite(endAngle) || endAngle <= startAngle) return [];
    const sortOrder = Number.isFinite(Number(row.sort_order)) ? Number(row.sort_order) : index + 1;
    const token = String(row.color_token ?? "");
    return [{
      code: String(row.code ?? row.label ?? ""),
      sector: String(row.label ?? ""),
      displayValue: String(row.display_value ?? ""),
      share: (endAngle - startAngle) / 360,
      offset: startAngle / 360,
      colorClass: `sector-color-${INDUSTRY_COLOR_CLASS[token] ?? ((sortOrder - 1) % 8) + 1}`,
    }];
  });
}

export function SectorDonut({ chart }: { chart?: SectorChartSnapshot }) {
  const slices = sectorSlices(chart);
  const description = String(chart?.alt_text ?? "")
    || slices.map((slice) => `${slice.sector} ${slice.displayValue}`).join(", ");

  return <figure className="sector-donut-figure">
    <svg className="sector-donut" viewBox="0 0 120 120" role="img" aria-labelledby="sector-donut-title sector-donut-desc">
      <title id="sector-donut-title">Index Sectors Breakdown</title>
      <desc id="sector-donut-desc">{description}</desc>
      <circle className="sector-donut-track" cx="60" cy="60" r="44" pathLength="100" />
      {slices.map((slice, index) => <circle
        key={`${slice.code}-${index}`}
        className={`sector-donut-slice ${slice.colorClass}`}
        cx="60"
        cy="60"
        r="44"
        pathLength="100"
        strokeDasharray={`${slice.share * 100} ${100 - slice.share * 100}`}
        strokeDashoffset={slice.offset * -100}
      />)}
    </svg>
    <figcaption className="sector-donut-legend">
      {slices.map((slice, index) => <span key={`${slice.code}-legend-${index}`}>
        <i className={`sector-swatch ${slice.colorClass}`} aria-hidden="true" />
        <b>{slice.sector}</b>
        <strong>{slice.displayValue}</strong>
      </span>)}
    </figcaption>
  </figure>;
}
