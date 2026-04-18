"use client";

import { useState, useMemo } from "react";
import { Chart } from "@/components/chart";
import { COUNTRIES } from "@/lib/indicators";
import Link from "next/link";

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

interface Stats {
  current: number;
  previous: number;
  change: number;
  allTimeHigh: number;
  allTimeLow: number;
  earliestDate: string;
  latestDate: string;
}

type TimeRange = "5y" | "10y" | "25y" | "max";

interface Props {
  indicator: Indicator;
  country: Country;
  dataPoints: DataPoint[];
  stats: Stats;
}

function formatValue(value: number, unit: string): string {
  if (unit.includes("%")) return `${value.toFixed(2)}%`;
  if (unit.includes("Billion")) return `$${value.toLocaleString("en-US", { maximumFractionDigits: 1 })}B`;
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

export function IndicatorDetail({ indicator, country, dataPoints, stats }: Props) {
  const [timeRange, setTimeRange] = useState<TimeRange>("max");

  const chartData = useMemo(
    () =>
      filterByTimeRange(dataPoints, timeRange).map((d) => ({
        time: d.date,
        value: d.value,
      })),
    [dataPoints, timeRange]
  );

  const ranges: { label: string; value: TimeRange }[] = [
    { label: "5Y", value: "5y" },
    { label: "10Y", value: "10y" },
    { label: "25Y", value: "25y" },
    { label: "Max", value: "max" },
  ];

  const isPositiveChange = stats.change >= 0;

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

      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-3">
            <span className="text-2xl">{country.flag_emoji}</span>
            <div>
              <h1 className="text-2xl font-bold">
                {country.name_de || country.name} — {indicator.name_de || indicator.name}
              </h1>
              <p className="text-sm text-muted-foreground">
                {indicator.name} &middot; {indicator.frequency} &middot; {indicator.unit}
              </p>
            </div>
          </div>
        </div>
        <div className="text-right">
          <div className="text-3xl font-bold">{formatValue(stats.current, indicator.unit)}</div>
          <div className={`text-sm font-medium ${isPositiveChange ? "text-green-500" : "text-red-500"}`}>
            {isPositiveChange ? "\u25B2" : "\u25BC"} {Math.abs(stats.change).toFixed(2)}% vs. previous
          </div>
          <div className="text-xs text-muted-foreground mt-1">
            {stats.latestDate} &middot; Source: {indicator.source_name}
          </div>
        </div>
      </div>

      {/* Key Stats Bar */}
      <div className="grid grid-cols-2 gap-px rounded-lg bg-border overflow-hidden sm:grid-cols-5">
        {[
          { label: "Current", value: formatValue(stats.current, indicator.unit) },
          { label: "Previous", value: formatValue(stats.previous, indicator.unit) },
          { label: "All-Time High", value: formatValue(stats.allTimeHigh, indicator.unit) },
          { label: "All-Time Low", value: formatValue(stats.allTimeLow, indicator.unit) },
          { label: "History", value: `${stats.earliestDate.slice(0, 4)}\u2013${stats.latestDate.slice(0, 4)}` },
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
        <Chart data={chartData} height={350} />
      </div>

      {/* Historical Data Table */}
      <div className="rounded-lg border bg-card p-4">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-medium">Historical Values</h2>
          <div className="text-xs text-muted-foreground">
            {dataPoints.length} data points
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
              {[...dataPoints]
                .reverse()
                .slice(0, 50)
                .map((dp, i, arr) => {
                  const prev = arr[i + 1];
                  const pctChange = prev
                    ? ((dp.value - prev.value) / Math.abs(prev.value)) * 100
                    : 0;
                  return (
                    <tr key={dp.date} className="border-b border-border/50 hover:bg-muted/30">
                      <td className="py-2 px-3">{dp.date}</td>
                      <td className="py-2 px-3 text-right font-mono">
                        {formatValue(dp.value, indicator.unit)}
                      </td>
                      <td
                        className={`py-2 px-3 text-right font-mono ${
                          pctChange >= 0 ? "text-green-500" : "text-red-500"
                        }`}
                      >
                        {prev ? `${pctChange >= 0 ? "+" : ""}${pctChange.toFixed(2)}%` : ""}
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Source Link */}
      {indicator.source_url && (
        <div className="text-xs text-muted-foreground">
          Source:{" "}
          <a
            href={indicator.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary hover:underline"
          >
            {indicator.source_name}
          </a>
        </div>
      )}
    </div>
  );
}
