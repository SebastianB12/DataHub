"use client";

import { Chart, type ChartOverlay } from "@/components/chart";

interface Series {
  country: string;
  label: string;
  flag: string;
  data: { date: string; value: number }[];
}

// Colors reused for legend + lines. Palette shared with the indicator-detail
// overlay colors so the visual language is consistent across pages.
const PALETTE = ["#818cf8", "#fb7185", "#4ade80", "#facc15", "#60a5fa", "#c084fc"];

interface Props {
  series: Series[];
}

export function DashboardCompareChart({ series }: Props) {
  if (series.length === 0) {
    return (
      <div className="h-64 flex items-center justify-center text-sm text-muted-foreground">
        Keine Daten
      </div>
    );
  }

  // Primary series = first entry (used as the Area chart base).
  const [primary, ...rest] = series;
  const primaryData = primary.data.map((d) => ({ time: d.date, value: d.value }));

  const overlays: ChartOverlay[] = rest.map((s, i) => ({
    label: s.label,
    data: s.data.map((d) => ({ time: d.date, value: d.value })),
    color: PALETTE[(i + 1) % PALETTE.length],
  }));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {series.map((s, i) => {
          const color = PALETTE[i % PALETTE.length];
          return (
            <span
              key={s.country}
              className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs"
              style={{ borderColor: color, color }}
            >
              {s.flag} {s.label}
            </span>
          );
        })}
      </div>
      <Chart data={primaryData} overlays={overlays} height={320} color={PALETTE[0]} />
    </div>
  );
}
