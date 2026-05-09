"use client";

import { useState, useMemo, useEffect } from "react";
import { Chart, type ChartOverlay } from "@/components/chart";
import { COUNTRIES } from "@/lib/indicators";
import { computeYoY, computePoP, type Frequency } from "@/lib/transforms";
import { exportCsv, exportXlsx } from "@/lib/export";
import { supabase } from "@/lib/supabase";
import { Download, X, Plus } from "lucide-react";
import Link from "next/link";

// Distinct colors for overlay country lines. Cycle if more than 5 overlays
// are ever added (unlikely in practice).
const OVERLAY_COLORS = ["#fb7185", "#4ade80", "#facc15", "#60a5fa", "#c084fc"];

interface Indicator {
  slug: string;
  name: string;
  name_de: string;
  category: string;
  unit: string;
  frequency: string;
  description: string;
  source_name: string;
  source_url: string;
}

interface Country {
  code: string;
  name: string;
  name_de: string;
  flag_emoji: string;
}

interface DataPoint {
  date: string;
  value: number;
}

interface VariantData {
  source: string;       // e.g. "destatis", "eurostat", "fred"
  adjustment: string;   // "SA" | "NSA" | ""
  frequency: Frequency;
  seriesId: string;
  unit: string;
  data: DataPoint[];
}

type TimeRange = "5y" | "10y" | "25y" | "max";
type DisplayMode = "raw" | "pop" | "yoy";

const FREQ_LABEL: Record<Frequency, string> = { M: "Monatlich", Q: "Quartalsweise", A: "Jährlich" };
const POP_LABEL: Record<Frequency, string> = { M: "% MoM", Q: "% QoQ", A: "% YoY" };
const FREQ_ORDER: Frequency[] = ["M", "Q", "A"];

interface Props {
  indicator: Indicator;
  country: Country;
  countryCode: string;
  variants: VariantData[];
  defaultSource: string;
  defaultAdjustment: string;
  defaultDisplay?: DisplayMode;
  relatedIndicators: { slug: string; name: string; name_de: string }[];
}

import { resolveSourceInfo, resolveSourceUrl } from "@/lib/sources";

function formatValue(value: number, unit: string): string {
  if (unit.includes("%")) return `${value.toFixed(2)}%`;
  if (unit.includes("Billion")) return `${value.toLocaleString("en-US", { maximumFractionDigits: 1 })}B`;
  if (unit.includes("Million")) return `${value.toLocaleString("en-US", { maximumFractionDigits: 0 })}M`;
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function filterByTimeRange(data: DataPoint[], range: TimeRange): DataPoint[] {
  if (range === "max") return data;
  const now = new Date();
  const years = range === "5y" ? 5 : range === "10y" ? 10 : 25;
  const cutoff = new Date(now.getFullYear() - years, now.getMonth(), now.getDate());
  return data.filter((d) => new Date(d.date) >= cutoff);
}


export function IndicatorDetail({ indicator, country, countryCode, variants, defaultSource, defaultAdjustment, defaultDisplay = "raw", relatedIndicators }: Props) {
  const [timeRange, setTimeRange] = useState<TimeRange>("max");
  const [selectedSource, setSelectedSource] = useState<string>(defaultSource);
  const [adjustment, setAdjustment] = useState<string>(defaultAdjustment);

  // Country overlays for chart comparison (on-demand loaded)
  const [overlayCountries, setOverlayCountries] = useState<string[]>([]);
  const [overlayData, setOverlayData] = useState<Record<string, DataPoint[]>>({});
  const [showCountryPicker, setShowCountryPicker] = useState(false);

  // All unique sources (default-source first, then alphabetical)
  const uniqueSources = useMemo(() => {
    const set = new Set(variants.map((v) => v.source));
    const list = Array.from(set);
    return list.sort((a, b) => {
      if (a === defaultSource && b !== defaultSource) return -1;
      if (b === defaultSource && a !== defaultSource) return 1;
      return a.localeCompare(b);
    });
  }, [variants, defaultSource]);

  // Available frequencies for the selected source (across all its variants)
  const availableFrequencies = useMemo<Frequency[]>(() => {
    const set = new Set<Frequency>();
    variants.filter((v) => v.source === selectedSource).forEach((v) => set.add(v.frequency));
    return FREQ_ORDER.filter((f) => set.has(f));
  }, [variants, selectedSource]);

  const defaultFrequency = availableFrequencies[0] || "M";
  const [frequency, setFrequency] = useState<Frequency>(defaultFrequency);

  // Reactive: if frequency vanishes after source switch, reset to finest available
  useEffect(() => {
    if (availableFrequencies.length === 0) return;
    if (!availableFrequencies.includes(frequency)) setFrequency(availableFrequencies[0]);
  }, [availableFrequencies, frequency]);

  // Available adjustments for the selected source + frequency
  const availableAdjustments = useMemo(() => {
    const set = new Set<string>();
    variants
      .filter((v) => v.source === selectedSource && v.frequency === frequency)
      .forEach((v) => set.add(v.adjustment || ""));
    return Array.from(set).sort();
  }, [variants, selectedSource, frequency]);

  useEffect(() => {
    if (availableAdjustments.length === 0) return;
    if (!availableAdjustments.includes(adjustment)) {
      const next =
        availableAdjustments.find((a) => a === "SA") ||
        availableAdjustments.find((a) => a === "NSA") ||
        availableAdjustments[0];
      setAdjustment(next);
    }
  }, [availableAdjustments, adjustment]);

  // Find the active variant (source + frequency + adjustment)
  const activeVariant = useMemo(() => {
    return (
      variants.find(
        (v) => v.source === selectedSource && v.frequency === frequency && (v.adjustment || "") === adjustment
      ) ||
      variants.find((v) => v.source === selectedSource && v.frequency === frequency) ||
      variants.find((v) => v.source === selectedSource) ||
      variants[0]
    );
  }, [variants, selectedSource, frequency, adjustment]);

  const baseData = activeVariant?.data || [];
  const baseUnit = activeVariant?.unit || "";
  const seriesId = activeVariant?.seriesId || "";
  const source = activeVariant?.source || "";

  // YoY makes sense for any frequency. PoP only when M or Q (at A it equals YoY).
  const supportsPoP = frequency !== "A";
  const initialDisplay: DisplayMode = defaultDisplay === "pop" && !supportsPoP ? "yoy" : defaultDisplay;
  const [displayMode, setDisplayMode] = useState<DisplayMode>(initialDisplay);

  // If frequency switches to A while displayMode=pop, fall back to YoY (semantically equal at A)
  useEffect(() => {
    if (!supportsPoP && displayMode === "pop") setDisplayMode("yoy");
  }, [supportsPoP, displayMode]);

  const activeData = useMemo(() => {
    if (displayMode === "yoy") return computeYoY(baseData, baseUnit);
    if (displayMode === "pop") return computePoP(baseData, baseUnit);
    return baseData;
  }, [baseData, baseUnit, displayMode]);

  const isRateBase = baseUnit.includes("%");
  const activeUnit =
    displayMode === "yoy" ? (isRateBase ? "pp YoY" : "% YoY")
    : displayMode === "pop" ? (isRateBase ? `pp ${POP_LABEL[frequency].slice(2)}` : POP_LABEL[frequency])
    : baseUnit;

  const chartData = useMemo(
    () =>
      filterByTimeRange(activeData, timeRange).map((d) => ({
        time: d.date,
        value: d.value,
      })),
    [activeData, timeRange]
  );

  // Fetch overlay country data on demand (cached in overlayData)
  useEffect(() => {
    const needed = overlayCountries.filter((c) => !overlayData[c]);
    if (needed.length === 0) return;
    let cancelled = false;
    (async () => {
      const results: Record<string, DataPoint[]> = {};
      for (const code of needed) {
        const { data } = await supabase
          .from("data_points_merged")
          .select("date, value, adjustment")
          .eq("indicator", indicator.slug)
          .eq("country", code)
          .order("date", { ascending: true });
        if (!data) continue;
        // Prefer rows whose adjustment matches the primary variant's adjustment.
        // Fall back to all rows if none match (e.g. other country only has NSA).
        const matched = data.filter((d) => (d.adjustment || "") === adjustment);
        const rows = matched.length > 0 ? matched : data;
        results[code] = rows.map((d) => ({ date: d.date, value: d.value }));
      }
      if (!cancelled && Object.keys(results).length > 0) {
        setOverlayData((prev) => ({ ...prev, ...results }));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [overlayCountries, overlayData, indicator.slug, adjustment]);

  const chartOverlays: ChartOverlay[] = useMemo(() => {
    const out: ChartOverlay[] = [];
    overlayCountries.forEach((code, idx) => {
      const raw = overlayData[code];
      if (!raw) return;
      const transformed =
        displayMode === "yoy" ? computeYoY(raw, baseUnit)
        : displayMode === "pop" ? computePoP(raw, baseUnit)
        : raw;
      const windowed = filterByTimeRange(transformed, timeRange);
      const country = COUNTRIES.find((c) => c.code === code);
      out.push({
        label: country?.name_de || code,
        data: windowed.map((d) => ({ time: d.date, value: d.value })),
        color: OVERLAY_COLORS[idx % OVERLAY_COLORS.length],
      });
    });
    return out;
  }, [overlayCountries, overlayData, displayMode, baseUnit, timeRange]);

  const availableOverlayCountries = COUNTRIES.filter(
    (c) => c.code !== countryCode.toUpperCase() && !overlayCountries.includes(c.code)
  );

  const activeStats = useMemo(() => {
    const values = activeData.map((d) => d.value);
    const latest = activeData[activeData.length - 1];
    const previous = activeData[activeData.length - 2];
    const isRate = activeUnit.includes("%");
    const change =
      latest && previous
        ? isRate
          ? Math.round((latest.value - previous.value) * 100) / 100
          : Math.round(((latest.value - previous.value) / Math.abs(previous.value)) * 10000) / 100
        : 0;
    return {
      current: latest?.value ?? 0,
      previous: previous?.value ?? 0,
      change,
      allTimeHigh: values.length ? Math.max(...values) : 0,
      allTimeLow: values.length ? Math.min(...values) : 0,
      earliestDate: activeData[0]?.date ?? "",
      latestDate: latest?.date ?? "",
    };
  }, [activeData, activeUnit]);

  const ranges: { label: string; value: TimeRange }[] = [
    { label: "5Y", value: "5y" },
    { label: "10Y", value: "10y" },
    { label: "25Y", value: "25y" },
    { label: "Max", value: "max" },
  ];

  const isPositiveChange = activeStats.change >= 0;
  const showAdjustmentToggle = availableAdjustments.length > 1;

  // relatedIndicators arrives pre-filtered from the server (same category, tier<=2)

  const countryInfo = COUNTRIES.find((c) => c.code.toLowerCase() === countryCode.toLowerCase());

  const sourceLabel = resolveSourceInfo(source, seriesId).label;
  const sourceUrl = resolveSourceUrl(source, seriesId) || null;

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="text-sm text-muted-foreground">
        <Link href="/indicators" className="text-primary hover:underline">
          Indicators
        </Link>
        <span className="mx-1">/</span>
        <Link href={`/indicators/${indicator.slug}`} className="text-primary hover:underline">
          {indicator.name_de || indicator.name}
        </Link>
        <span className="mx-1">/</span>
        <span>{country.name_de || country.name}</span>
      </div>

      {/* Country Switcher */}
      <div className="flex items-center gap-1 flex-wrap">
        {COUNTRIES.map((c) => {
          const isActive = c.code.toLowerCase() === countryCode.toLowerCase();
          return (
            <Link
              key={c.code}
              href={`/indicators/${indicator.slug}/${c.code.toLowerCase()}`}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors ${
                isActive
                  ? "bg-primary text-primary-foreground font-medium"
                  : "bg-muted text-muted-foreground hover:bg-muted/70"
              }`}
            >
              <span>{c.flag}</span>
              {c.name_de}
            </Link>
          );
        })}
        <Link
          href={`/indicators/${indicator.slug}`}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm bg-muted text-muted-foreground hover:bg-muted/70 transition-colors ml-1"
        >
          Alle vergleichen
        </Link>
      </div>

      {/* Source + Display Mode + Adjustment Toggles */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Source Selector */}
        {uniqueSources.length > 1 && (
          <div className="flex items-center gap-2">
            <label htmlFor="source-select" className="text-xs text-muted-foreground">Quelle:</label>
            <select
              id="source-select"
              value={selectedSource}
              onChange={(e) => setSelectedSource(e.target.value)}
              className="rounded-md bg-muted border border-border text-foreground px-3 py-1.5 text-sm font-medium hover:bg-muted/70 transition-colors cursor-pointer"
            >
              {uniqueSources.map((src) => {
                const sample = variants.find((v) => v.source === src);
                return (
                  <option key={src} value={src}>
                    {resolveSourceInfo(src, sample?.seriesId || "").label}
                  </option>
                );
              })}
            </select>
          </div>
        )}

        {/* Frequency Toggle */}
        {availableFrequencies.length > 1 && (
          <div className="flex items-center gap-1">
            {FREQ_ORDER.map((f) => {
              const enabled = availableFrequencies.includes(f);
              return (
                <button
                  key={f}
                  onClick={() => enabled && setFrequency(f)}
                  disabled={!enabled}
                  title={enabled ? FREQ_LABEL[f] : `${FREQ_LABEL[f]} nicht verfügbar`}
                  className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                    frequency === f
                      ? "bg-primary text-primary-foreground font-medium"
                      : enabled
                      ? "bg-muted text-muted-foreground hover:bg-muted/70"
                      : "bg-muted/40 text-muted-foreground/40 cursor-not-allowed"
                  }`}
                >
                  {FREQ_LABEL[f]}
                </button>
              );
            })}
          </div>
        )}

        {/* Display Mode Toggle */}
        <div className="flex items-center gap-1">
          {(
            [
              { label: baseUnit || "Raw", value: "raw" as DisplayMode, show: true },
              { label: POP_LABEL[frequency], value: "pop" as DisplayMode, show: supportsPoP },
              { label: "% YoY", value: "yoy" as DisplayMode, show: true },
            ] as const
          )
            .filter((m) => m.show)
            .map((m) => (
              <button
                key={m.value}
                onClick={() => setDisplayMode(m.value)}
                className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                  displayMode === m.value
                    ? "bg-primary text-primary-foreground font-medium"
                    : "bg-muted text-muted-foreground hover:bg-muted/70"
                }`}
              >
                {m.label}
              </button>
            ))}
        </div>

        {/* Adjustment Toggle (only when source has multiple adjustments) */}
        {showAdjustmentToggle && (
          <div className="flex items-center gap-1">
            {availableAdjustments.map((adj) => (
              <button
                key={adj}
                onClick={() => setAdjustment(adj)}
                className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                  adjustment === adj
                    ? "bg-primary text-primary-foreground font-medium"
                    : "bg-muted text-muted-foreground hover:bg-muted/70"
                }`}
              >
                {adj || "—"}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-3">
            <span className="text-2xl">{countryInfo?.flag ?? country.flag_emoji}</span>
            <div>
              <h1 className="text-2xl font-bold">
                {country.name_de || country.name} — {indicator.name_de || indicator.name}
              </h1>
              <p className="text-sm text-muted-foreground">
                {indicator.name} &middot; {indicator.frequency} &middot; {baseUnit || indicator.unit}
              </p>
            </div>
          </div>
        </div>
        <div className="text-right">
          <div className="text-3xl font-bold">{formatValue(activeStats.current, activeUnit)}</div>
          <div className={`text-sm font-medium ${isPositiveChange ? "text-green-500" : "text-red-500"}`}>
            {isPositiveChange ? "\u25B2" : "\u25BC"} {Math.abs(activeStats.change).toFixed(2)}{activeUnit.includes("%") ? " pp" : "%"} vs. previous
          </div>
          <div className="text-xs text-muted-foreground mt-1">
            {activeStats.latestDate} &middot; Source:{" "}
            {sourceUrl ? (
              <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">{sourceLabel}</a>
            ) : (
              <span>{sourceLabel}</span>
            )}
            {seriesId && <span className="ml-1 font-mono text-muted-foreground/70">({seriesId})</span>}
          </div>
        </div>
      </div>

      {/* Key Stats Bar */}
      <div className="grid grid-cols-2 gap-px rounded-lg bg-border overflow-hidden sm:grid-cols-5">
        {[
          { label: "Current", value: formatValue(activeStats.current, activeUnit) },
          { label: "Previous", value: formatValue(activeStats.previous, activeUnit) },
          { label: "All-Time High", value: formatValue(activeStats.allTimeHigh, activeUnit) },
          { label: "All-Time Low", value: formatValue(activeStats.allTimeLow, activeUnit) },
          { label: "History", value: `${activeStats.earliestDate.slice(0, 4)}\u2013${activeStats.latestDate.slice(0, 4)}` },
        ].map((stat) => (
          <div key={stat.label} className="bg-card p-3 text-center">
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
              {stat.label}
            </div>
            <div className="mt-1 text-sm font-semibold">{stat.value}</div>
          </div>
        ))}
      </div>

      {/* Description */}
      {indicator.description && (
        <p className="text-sm text-muted-foreground leading-relaxed">
          {indicator.description}
        </p>
      )}

      {/* Chart */}
      <div className="rounded-lg border bg-card p-4">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-medium">Historical Data</h2>
          <div className="flex gap-1">
            {ranges.map((r) => (
              <button
                key={r.value}
                onClick={() => setTimeRange(r.value)}
                className={`px-2.5 py-1 text-xs rounded transition-colors ${
                  timeRange === r.value
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:bg-muted/80"
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <span className="text-xs text-muted-foreground">Vergleichen:</span>
          <span className="inline-flex items-center gap-1 rounded-md bg-primary/15 border border-primary/30 px-2 py-0.5 text-xs">
            {country.flag_emoji} {country.name_de || country.name}
          </span>
          {overlayCountries.map((code, idx) => {
            const c = COUNTRIES.find((x) => x.code === code);
            const color = OVERLAY_COLORS[idx % OVERLAY_COLORS.length];
            return (
              <span
                key={code}
                className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs"
                style={{ borderColor: color, color }}
              >
                {c?.flag} {c?.name_de || code}
                <button
                  type="button"
                  onClick={() =>
                    setOverlayCountries((prev) => prev.filter((x) => x !== code))
                  }
                  className="hover:opacity-70"
                  aria-label="Entfernen"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            );
          })}
          {availableOverlayCountries.length > 0 && (
            <div className="relative">
              <button
                type="button"
                onClick={() => setShowCountryPicker((o) => !o)}
                className="inline-flex items-center gap-1 rounded-md border border-dashed border-border px-2 py-0.5 text-xs text-muted-foreground hover:bg-muted/50"
              >
                <Plus className="h-3 w-3" /> Land
              </button>
              {showCountryPicker && (
                <div className="absolute z-20 mt-1 rounded-md border border-border bg-popover shadow-lg">
                  {availableOverlayCountries.map((c) => (
                    <button
                      key={c.code}
                      type="button"
                      onClick={() => {
                        setOverlayCountries((prev) => [...prev, c.code]);
                        setShowCountryPicker(false);
                      }}
                      className="flex w-full items-center gap-2 px-3 py-1.5 text-xs hover:bg-muted/50 whitespace-nowrap"
                    >
                      {c.flag} {c.name_de}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
        <Chart data={chartData} overlays={chartOverlays} height={350} />
      </div>

      {/* Historical Data Table */}
      <div className="rounded-lg border bg-card p-4">
        <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
          <h2 className="text-sm font-medium">Historical Values</h2>
          <div className="flex items-center gap-3">
            <div className="text-xs text-muted-foreground">
              {activeData.length} data points
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => {
                  const base = `${indicator.slug}-${countryCode.toLowerCase()}-${selectedSource}${adjustment ? "-" + adjustment : ""}-${displayMode}`;
                  const columnLabel = `${indicator.name_de || indicator.name} (${activeUnit})`;
                  exportCsv(activeData, { filenameBase: base, columnLabel });
                }}
                className="flex items-center gap-1 rounded-md border border-border bg-muted/40 px-2 py-1 text-xs hover:bg-muted transition-colors"
                title="Als CSV herunterladen"
              >
                <Download className="h-3 w-3" />
                CSV
              </button>
              <button
                type="button"
                onClick={() => {
                  const base = `${indicator.slug}-${countryCode.toLowerCase()}-${selectedSource}${adjustment ? "-" + adjustment : ""}-${displayMode}`;
                  const columnLabel = `${indicator.name_de || indicator.name} (${activeUnit})`;
                  exportXlsx(activeData, { filenameBase: base, columnLabel });
                }}
                className="flex items-center gap-1 rounded-md border border-border bg-muted/40 px-2 py-1 text-xs hover:bg-muted transition-colors"
                title="Als Excel herunterladen"
              >
                <Download className="h-3 w-3" />
                Excel
              </button>
            </div>
          </div>
        </div>
        <div className="overflow-auto max-h-96">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-card">
              <tr className="border-b">
                <th className="text-left py-2 px-3 font-medium text-muted-foreground">Date</th>
                <th className="text-right py-2 px-3 font-medium text-muted-foreground">Value</th>
                <th className="text-right py-2 px-3 font-medium text-muted-foreground">Change</th>
              </tr>
            </thead>
            <tbody>
              {[...activeData]
                .reverse()
                .slice(0, 50)
                .map((dp, i, arr) => {
                  const prev = arr[i + 1];
                  const isRate = activeUnit.includes("%");
                  const diff = prev
                    ? isRate
                      ? dp.value - prev.value
                      : ((dp.value - prev.value) / Math.abs(prev.value)) * 100
                    : 0;
                  const diffLabel = isRate ? "pp" : "%";
                  return (
                    <tr key={dp.date} className="border-b border-border/50 hover:bg-muted/30">
                      <td className="py-2 px-3">{dp.date}</td>
                      <td className="py-2 px-3 text-right font-mono">
                        {formatValue(dp.value, activeUnit)}
                      </td>
                      <td
                        className={`py-2 px-3 text-right font-mono ${
                          diff >= 0 ? "text-green-500" : "text-red-500"
                        }`}
                      >
                        {prev ? `${diff >= 0 ? "+" : ""}${diff.toFixed(2)}${diffLabel}` : ""}
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Related Indicators */}
      {relatedIndicators.length > 0 && (
        <div className="rounded-lg border bg-card p-4">
          <h2 className="text-sm font-medium mb-3">
            Weitere in {indicator.category}
          </h2>
          <div className="flex gap-2 flex-wrap">
            {relatedIndicators.map((ind) => (
              <Link
                key={ind.slug}
                href={`/indicators/${ind.slug}/${countryCode.toLowerCase()}`}
                className="rounded-md bg-muted px-3 py-1.5 text-xs hover:bg-muted/70 transition-colors"
              >
                {ind.name_de}
              </Link>
            ))}
          </div>
        </div>
      )}

      {/* Source Link Footer */}
      <div className="text-xs text-muted-foreground">
        Source:{" "}
        {sourceUrl ? (
          <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
            {sourceLabel}
          </a>
        ) : (
          <span>{sourceLabel}</span>
        )}
        {seriesId && (
          <span className="ml-1 text-muted-foreground/70">
            &middot; Serie: <span className="font-mono">{seriesId}</span>
          </span>
        )}
        {baseUnit && (
          <span className="ml-1 text-muted-foreground/70">
            &middot; Einheit: {baseUnit}
          </span>
        )}
        {adjustment && (
          <span className="ml-1 text-muted-foreground/70">
            &middot; {adjustment === "SA" ? "Saisonbereinigt" : adjustment === "NSA" ? "Unbereinigt" : adjustment}
          </span>
        )}
      </div>
    </div>
  );
}
