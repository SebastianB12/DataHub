export interface DataPoint {
  date: string;
  value: number;
}

/**
 * Compute year-over-year change from a time series.
 * Uses UTC year/month matching so it's timezone-safe and tolerates gaps.
 * For rate-like units (containing "%"): absolute difference in percentage points.
 * For levels/indices: relative percent change.
 * Drops points where the prior-year value is missing or zero.
 */
export function computeYoY(data: DataPoint[], unit: string = ""): DataPoint[] {
  const isRate = unit.includes("%");
  const byYearMonth = new Map<string, number>();
  for (const d of data) {
    const dt = new Date(d.date);
    const key = `${dt.getUTCFullYear()}-${String(dt.getUTCMonth() + 1).padStart(2, "0")}`;
    byYearMonth.set(key, d.value);
  }

  const result: DataPoint[] = [];
  for (const d of data) {
    const dt = new Date(d.date);
    const prevKey = `${dt.getUTCFullYear() - 1}-${String(dt.getUTCMonth() + 1).padStart(2, "0")}`;
    const prevValue = byYearMonth.get(prevKey);
    if (prevValue === undefined || prevValue === 0) continue;
    const change = isRate ? d.value - prevValue : ((d.value - prevValue) / Math.abs(prevValue)) * 100;
    result.push({ date: d.date, value: Math.round(change * 100) / 100 });
  }
  return result;
}

/**
 * Latest YoY value from a series (or undefined if no valid match).
 * Useful for overview widgets that only need the most recent point.
 */
export function latestYoY(data: DataPoint[]): DataPoint | undefined {
  const yoy = computeYoY(data);
  return yoy.length > 0 ? yoy[yoy.length - 1] : undefined;
}

export type Frequency = "M" | "Q" | "A";

/**
 * Heuristically detect the frequency of a time series by looking at the
 * median gap between consecutive points. Robust against missing months and
 * outliers (e.g. one accidental duplicate row).
 */
export function detectFrequency(data: DataPoint[]): Frequency | null {
  if (data.length < 2) return null;
  const gaps: number[] = [];
  for (let i = 1; i < data.length; i++) {
    const a = new Date(data[i - 1].date).getTime();
    const b = new Date(data[i].date).getTime();
    gaps.push((b - a) / (1000 * 60 * 60 * 24));
  }
  gaps.sort((a, b) => a - b);
  const median = gaps[Math.floor(gaps.length / 2)];
  if (median < 45) return "M";
  if (median < 150) return "Q";
  return "A";
}

/**
 * Period-over-period percent change. For rate-like units (containing "%")
 * we return absolute differences in percentage points; otherwise relative %.
 * Drops points where the prior value is missing or zero.
 */
export function computePoP(data: DataPoint[], unit: string): DataPoint[] {
  const isRate = unit.includes("%");
  const result: DataPoint[] = [];
  for (let i = 1; i < data.length; i++) {
    const prev = data[i - 1].value;
    const curr = data[i].value;
    if (prev === 0 || prev === undefined || curr === undefined) continue;
    const change = isRate ? curr - prev : ((curr - prev) / Math.abs(prev)) * 100;
    result.push({ date: data[i].date, value: Math.round(change * 100) / 100 });
  }
  return result;
}
