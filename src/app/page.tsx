import { supabase } from "@/lib/supabase";
import Link from "next/link";
import { INDEX_INDICATORS, YOY_UNIT, COUNTRIES } from "@/lib/indicators";
import { latestYoY } from "@/lib/transforms";
import { DashboardCompareChart } from "@/components/dashboard-compare-chart";

export const revalidate = 1800; // ISR: 30 min

interface MergedRow {
  indicator: string;
  country: string;
  date: string;
  value: number;
  unit: string | null;
}

interface ReleaseRow {
  indicator: string;
  country: string;
  date: string;
  value: number;
  unit: string | null;
}

async function getDashboardData() {
  const headlineIndicators = ["gdp", "inflation-cpi", "interest-rate", "unemployment"];
  const compareIndicator = "inflation-cpi";
  const compareCountries = COUNTRIES.map((c) => c.code);
  const indexIndicators = Array.from(INDEX_INDICATORS);

  // 14 months back — enough to compute YoY for every monthly index series.
  const yoyCutoff = new Date();
  yoyCutoff.setMonth(yoyCutoff.getMonth() - 15);
  const yoyCutoffStr = yoyCutoff.toISOString().slice(0, 10);

  const [headlineRes, compareRes, releasesRes, indexHistoryRes] = await Promise.all([
    // Headline metrics (US)
    supabase
      .from("data_points_merged")
      .select("indicator, country, date, value, unit")
      .eq("country", "US")
      .in("indicator", headlineIndicators)
      .order("date", { ascending: false }),
    // Inflation comparison across all countries
    supabase
      .from("data_points_merged")
      .select("indicator, country, date, value, unit")
      .eq("indicator", compareIndicator)
      .in("country", compareCountries)
      .order("date", { ascending: true }),
    // Most-recent observation per (indicator, country). Sort by data `date`
    // (not fetched_at) so the feed reflects publication recency, not pipeline
    // recency. 500 rows is enough to dedupe down to ~80 distinct series.
    supabase
      .from("data_points_merged")
      .select("indicator, country, date, value, unit")
      .order("date", { ascending: false })
      .limit(500),
    // Extra history for index indicators across all countries, so the Release
    // feed can show YoY (consistent with the headline cards above it).
    supabase
      .from("data_points_merged")
      .select("indicator, country, date, value")
      .in("indicator", indexIndicators)
      .in("country", compareCountries)
      .gte("date", yoyCutoffStr)
      .order("date", { ascending: true }),
  ]);

  const headline = (headlineRes.data || []) as MergedRow[];
  const compare = (compareRes.data || []) as MergedRow[];
  const allReleases = (releasesRes.data || []) as ReleaseRow[];
  const indexHistory = (indexHistoryRes.data || []) as MergedRow[];

  // Build YoY lookup per (indicator, country) for INDEX_INDICATORS
  const yoyByKey = new Map<string, { value: number; date: string }>();
  const historyByKey = new Map<string, { date: string; value: number }[]>();
  for (const row of indexHistory) {
    const key = `${row.indicator}:${row.country}`;
    if (!historyByKey.has(key)) historyByKey.set(key, []);
    historyByKey.get(key)!.push({ date: row.date, value: row.value });
  }
  for (const [key, rows] of historyByKey.entries()) {
    // Dedupe dates (merged view can contain multiple adjustments)
    const byDate = new Map<string, number>();
    for (const r of rows) if (!byDate.has(r.date)) byDate.set(r.date, r.value);
    const unique = Array.from(byDate.entries()).map(([date, value]) => ({ date, value }));
    const yoy = latestYoY(unique);
    if (yoy) yoyByKey.set(key, yoy);
  }

  // Dedupe to one latest row per (indicator, country), keep up to 15 most recent
  const seen = new Set<string>();
  const releases: ReleaseRow[] = [];
  for (const r of allReleases) {
    const key = `${r.indicator}:${r.country}`;
    if (seen.has(key)) continue;
    seen.add(key);
    // For index indicators, replace the raw value with latest YoY
    if (INDEX_INDICATORS.has(r.indicator)) {
      const yoy = yoyByKey.get(key);
      if (yoy) {
        releases.push({ ...r, value: yoy.value, date: yoy.date, unit: YOY_UNIT });
      }
      // If no YoY available (not enough history), skip this release entirely
      // rather than showing a confusing raw index value.
    } else {
      releases.push(r);
    }
    if (releases.length >= 15) break;
  }

  // Headline: latest value (or YoY) per indicator
  const headlineByIndicator: Record<string, { value: number; date: string; unit: string }> = {};
  const headlineRowsByIndicator: Record<string, MergedRow[]> = {};
  for (const row of headline) {
    if (!headlineRowsByIndicator[row.indicator]) headlineRowsByIndicator[row.indicator] = [];
    headlineRowsByIndicator[row.indicator].push(row);
  }
  for (const [indicator, rows] of Object.entries(headlineRowsByIndicator)) {
    if (INDEX_INDICATORS.has(indicator)) {
      const asc = [...rows].reverse().map((r) => ({ date: r.date, value: r.value }));
      const yoy = latestYoY(asc);
      if (yoy) headlineByIndicator[indicator] = { value: yoy.value, date: yoy.date, unit: YOY_UNIT };
    } else {
      const latest = rows[0];
      headlineByIndicator[indicator] = { value: latest.value, date: latest.date, unit: latest.unit || "" };
    }
  }

  // Comparison chart: build YoY series per country
  const seriesByCountry: Record<string, { date: string; value: number }[]> = {};
  for (const row of compare) {
    if (!seriesByCountry[row.country]) seriesByCountry[row.country] = [];
    seriesByCountry[row.country].push({ date: row.date, value: row.value });
  }
  const compareSeries = COUNTRIES.map((country) => {
    const raw = seriesByCountry[country.code] || [];
    // Deduplicate dates (multiple adjustments may exist in merged view)
    const byDate = new Map<string, number>();
    for (const d of raw) if (!byDate.has(d.date)) byDate.set(d.date, d.value);
    const unique = Array.from(byDate.entries()).map(([date, value]) => ({ date, value }));
    // Dashboard comparison always shown as YoY for inflation
    const yoySeries = INDEX_INDICATORS.has(compareIndicator)
      ? (() => {
          const byYearMonth = new Map<string, number>();
          for (const d of unique) {
            const dt = new Date(d.date);
            const key = `${dt.getUTCFullYear()}-${String(dt.getUTCMonth() + 1).padStart(2, "0")}`;
            byYearMonth.set(key, d.value);
          }
          const result: { date: string; value: number }[] = [];
          for (const d of unique) {
            const dt = new Date(d.date);
            const prevKey = `${dt.getUTCFullYear() - 1}-${String(dt.getUTCMonth() + 1).padStart(2, "0")}`;
            const prev = byYearMonth.get(prevKey);
            if (prev !== undefined && prev !== 0) {
              result.push({
                date: d.date,
                value: Math.round(((d.value - prev) / Math.abs(prev)) * 10000) / 100,
              });
            }
          }
          return result;
        })()
      : unique;
    return {
      country: country.code,
      label: country.name_de,
      flag: country.flag,
      data: yoySeries,
    };
  }).filter((s) => s.data.length > 0);

  return { headlineByIndicator, compareSeries, compareIndicator, releases };
}

function formatReleaseValue(value: number, unit: string | null): string {
  // Only glue "%" onto the number for the plain percent unit. Descriptive
  // variants like "% YoY" or "% of GDP" are shown as separate chips.
  if (!unit) return value.toString();
  if (unit === "%") return `${value.toFixed(2)}%`;
  if (unit.includes("Billion")) return `${value.toLocaleString("en-US", { maximumFractionDigits: 1 })}B`;
  if (unit.includes("Million")) return `${value.toLocaleString("en-US", { maximumFractionDigits: 0 })}M`;
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function unitSuffix(unit: string | null): string {
  if (!unit) return "";
  if (unit === "%") return ""; // already glued onto the value
  return unit;
}

export default async function Dashboard() {
  const { headlineByIndicator, compareSeries, compareIndicator, releases } = await getDashboardData();

  const headlineCards = [
    { label: "US GDP", slug: "gdp" },
    { label: "US Inflation", slug: "inflation-cpi" },
    { label: "Fed Funds Rate", slug: "interest-rate" },
    { label: "US Unemployment", slug: "unemployment" },
  ];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Key macroeconomic indicators at a glance
        </p>
      </div>

      {/* Key Metrics Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {headlineCards.map((card) => {
          const data = headlineByIndicator[card.slug];
          return (
            <Link
              key={card.slug}
              href={`/indicators/${card.slug}/us`}
              className="rounded-lg border bg-card p-4 hover:bg-muted/30 transition-colors"
            >
              <div className="text-xs text-muted-foreground uppercase tracking-wide">
                {card.label}
              </div>
              <div className="text-2xl font-bold mt-2">
                {data
                  ? `${data.value.toLocaleString("en-US", { maximumFractionDigits: 2 })}${data.unit.includes("%") ? "" : ""}`
                  : "\u2014"}
                {data && <span className="text-base font-medium text-muted-foreground ml-1">{data.unit}</span>}
              </div>
              <div className="text-xs text-muted-foreground mt-1">{data?.date || ""}</div>
            </Link>
          );
        })}
      </div>

      {/* Comparison Chart */}
      <div className="rounded-lg border bg-card p-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-sm font-medium">Inflation im Ländervergleich</h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Jährliche CPI-Veränderung (% YoY) für alle erfassten Länder
            </p>
          </div>
          <Link
            href={`/indicators/${compareIndicator}`}
            className="text-xs text-primary hover:underline"
          >
            Alle Länder →
          </Link>
        </div>
        <DashboardCompareChart series={compareSeries} />
      </div>

      {/* Latest Releases Feed */}
      <div className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium mb-3">Letzte Veröffentlichungen</h2>
        <div className="divide-y divide-border/50">
          {releases.map((r, i) => {
            const country = COUNTRIES.find((c) => c.code === r.country);
            return (
              <Link
                key={`${r.indicator}-${r.country}-${r.date}-${i}`}
                href={`/indicators/${r.indicator}/${r.country.toLowerCase()}`}
                className="flex items-center justify-between py-2 text-sm hover:bg-muted/30 -mx-2 px-2 rounded"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="shrink-0">{country?.flag || "🌐"}</span>
                  <span className="truncate">{r.indicator}</span>
                  <span className="text-xs text-muted-foreground shrink-0">· {r.date}</span>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  <span className="font-mono">{formatReleaseValue(r.value, r.unit)}</span>
                  {unitSuffix(r.unit) && (
                    <span className="text-xs text-muted-foreground">{unitSuffix(r.unit)}</span>
                  )}
                </div>
              </Link>
            );
          })}
        </div>
      </div>

      {/* Quick Links */}
      <div className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium mb-3">Explore Indicators</h2>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          {[
            { label: "GDP", slug: "gdp" },
            { label: "Inflation", slug: "inflation-cpi" },
            { label: "Core CPI", slug: "core-cpi" },
            { label: "Unemployment", slug: "unemployment" },
            { label: "Interest Rate", slug: "interest-rate" },
            { label: "Trade Balance", slug: "trade-balance" },
            { label: "PPI", slug: "ppi" },
            { label: "M2 Money Supply", slug: "money-supply-m2" },
            { label: "Gov. Debt", slug: "government-debt" },
            { label: "Exports", slug: "exports" },
            { label: "Imports", slug: "imports" },
            { label: "Population", slug: "population" },
          ].map((item) => (
            <Link
              key={item.slug}
              href={`/indicators/${item.slug}`}
              className="rounded-md bg-muted px-3 py-2 text-xs text-center hover:bg-muted/70 transition-colors"
            >
              {item.label}
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
