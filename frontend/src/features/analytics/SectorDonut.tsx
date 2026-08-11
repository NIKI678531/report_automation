interface SectorRow {
  code?: unknown;
  sector?: unknown;
  weight?: unknown;
}

interface SectorSlice {
  code: string;
  sector: string;
  weight: number;
  share: number;
  offset: number;
  colorIndex: number;
}

interface SectorChartSnapshot {
  slices?: unknown;
}

function formatPercent(value: number): string {
  return new Intl.NumberFormat("en-HK", {
    style: "percent",
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(value);
}

export function sectorSlices(sectors: SectorRow[], chart?: SectorChartSnapshot): SectorSlice[] {
  if (Array.isArray(chart?.slices)) {
    const snapshot = chart.slices.flatMap((value, index) => {
      if (!value || typeof value !== "object") return [];
      const row = value as Record<string, unknown>;
      const weight = Number(row.weight);
      const startAngle = Number(row.start_angle);
      const endAngle = Number(row.end_angle);
      if (!Number.isFinite(weight) || weight <= 0 || !Number.isFinite(startAngle) || !Number.isFinite(endAngle) || endAngle <= startAngle) return [];
      return [{
        code: String(row.code ?? row.label ?? ""),
        sector: String(row.label ?? ""),
        weight,
        share: (endAngle - startAngle) / 360,
        offset: startAngle / 360,
        colorIndex: Number.isInteger(Number(row.color_index)) ? Number(row.color_index) : index,
      }];
    });
    if (snapshot.length) return snapshot;
  }
  const rows = sectors.flatMap((row) => {
    const weight = Number(row.weight);
    return Number.isFinite(weight) && weight > 0
      ? [{ code: String(row.code ?? row.sector ?? ""), sector: String(row.sector ?? ""), weight }]
      : [];
  });
  const total = rows.reduce((sum, row) => sum + row.weight, 0);
  let offset = 0;
  return rows.map((row, index) => {
    const share = row.weight / total;
    const slice = { ...row, share, offset, colorIndex: index };
    offset += share;
    return slice;
  });
}

export function SectorDonut({ sectors, chart }: { sectors: SectorRow[]; chart?: SectorChartSnapshot }) {
  const slices = sectorSlices(sectors, chart);
  const description = slices.map((slice) => `${slice.sector} ${formatPercent(slice.share)}`).join(", ");

  return <figure className="sector-donut-figure">
    <svg className="sector-donut" viewBox="0 0 120 120" role="img" aria-labelledby="sector-donut-title sector-donut-desc">
      <title id="sector-donut-title">Index Sectors Breakdown</title>
      <desc id="sector-donut-desc">{description}</desc>
      <circle className="sector-donut-track" cx="60" cy="60" r="44" pathLength="100" />
      {slices.map((slice, index) => <circle
        key={`${slice.code}-${index}`}
        className={`sector-donut-slice sector-color-${slice.colorIndex % 8 + 1}`}
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
        <i className={`sector-swatch sector-color-${slice.colorIndex % 8 + 1}`} aria-hidden="true" />
        <b>{slice.sector}</b>
        <strong>{formatPercent(slice.weight)}</strong>
      </span>)}
    </figcaption>
  </figure>;
}