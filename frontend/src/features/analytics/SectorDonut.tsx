import { useLocale, type Locale } from "../../i18n";

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
  "industry.gics.10": 6,
  "industry.gics.15": 7,
  "industry.gics.20": 8,
  "industry.gics.25": 1,
  "industry.gics.30": 4,
  "industry.gics.35": 5,
  "industry.gics.40": 6,
  "industry.gics.45": 2,
  "industry.gics.50": 3,
  "industry.gics.55": 7,
  "industry.gics.60": 8,
};

function isUnclassified(row: Record<string, unknown>): boolean {
  if (String(row.code ?? "").trim().toUpperCase() === "UNCLASSIFIED") return true;
  return [row.label, row.label_zh_hans, row.label_zh_hant]
    .some((value) => ["unclassified", "未分类", "未分類"].includes(String(value ?? "").trim().toLowerCase()));
}

/**
 * Read the `industry_breakdown` chart snapshot. Order, the zero-weight filter, the percentage
 * string and the colour identity are all decided by the backend; the browser only turns angles
 * into stroke geometry. It must never recompute a number that appears on screen.
 */
export function sectorSlices(chart?: SectorChartSnapshot, locale: Locale = "en"): SectorSeriesEntry[] {
  if (!Array.isArray(chart?.series)) return [];
  return chart.series.flatMap((value, index) => {
    if (!value || typeof value !== "object") return [];
    const row = value as Record<string, unknown>;
    // Older saved snapshots can still contain the retired bucket. New snapshots omit it at the
    // source calculation, while this guard ensures the product page never exposes stale data.
    if (isUnclassified(row)) return [];
    const startAngle = Number(row.start_angle);
    const endAngle = Number(row.end_angle);
    if (!Number.isFinite(startAngle) || !Number.isFinite(endAngle) || endAngle <= startAngle) return [];
    const sortOrder = Number.isFinite(Number(row.sort_order)) ? Number(row.sort_order) : index + 1;
    const token = String(row.color_token ?? "");
    return [{
      code: String(row.code ?? row.label ?? ""),
      sector: String(locale === "zh-Hans" ? (row.label_zh_hans ?? "") : locale === "zh-Hant" ? (row.label_zh_hant ?? "") : (row.label ?? "")),
      displayValue: String(row.display_value ?? ""),
      share: (endAngle - startAngle) / 360,
      offset: startAngle / 360,
      colorClass: `sector-color-${INDUSTRY_COLOR_CLASS[token] ?? ((sortOrder - 1) % 8) + 1}`,
    }];
  });
}

export function SectorDonut({ chart, title }: { chart?: SectorChartSnapshot; title: string }) {
  const { locale } = useLocale();
  const slices = sectorSlices(chart, locale);
  const description = `${title}${locale === "en" ? ": " : "："}${slices.map((slice) => `${slice.sector} ${slice.displayValue}`).join(locale === "en" ? ", " : "，")}`;

  return <figure className="sector-donut-figure">
    <svg className="sector-donut" viewBox="0 0 120 120" role="img" aria-labelledby="sector-donut-title sector-donut-desc">
      <title id="sector-donut-title">{title}</title>
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
