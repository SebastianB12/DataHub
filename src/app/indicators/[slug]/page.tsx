import { supabase } from "@/lib/supabase";
import { notFound } from "next/navigation";
import Link from "next/link";
import { COUNTRIES, INDEX_INDICATORS, YOY_UNIT } from "@/lib/indicators";
import { latestYoY } from "@/lib/transforms";

export const revalidate = 3600;

interface Props {
  params: Promise<{ slug: string }>;
}

interface MergedRow {
  country: string;
  date: string;
  value: number;
  unit: string | null;
}

export default async function IndicatorOverviewPage({ params }: Props) {
  const { slug } = await params;

  const [indicatorRes, dataRes] = await Promise.all([
    supabase.from("indicators").select("*").eq("slug", slug).single(),
    supabase
      .from("data_points_merged")
      .select("country, date, value, unit")
      .eq("indicator", slug)
      .order("date", { ascending: false }),
  ]);

  if (indicatorRes.error || !indicatorRes.data) notFound();

  const indicator = indicatorRes.data;
  const isIndex = INDEX_INDICATORS.has(slug);

  const rowsByCountry: Record<string, MergedRow[]> = {};
  for (const row of (dataRes.data || []) as MergedRow[]) {
    (rowsByCountry[row.country] ||= []).push(row);
  }

  // Headline pro Land: YoY% für Index-Indikatoren, sonst latest raw value mit per-row unit.
  const headlineByCountry: Record<string, { value: number; date: string; unit: string }> = {};
  for (const [country, rows] of Object.entries(rowsByCountry)) {
    if (isIndex) {
      const asc = [...rows].reverse().map((r) => ({ date: r.date, value: r.value }));
      const yoy = latestYoY(asc);
      if (yoy) headlineByCountry[country] = { value: yoy.value, date: yoy.date, unit: YOY_UNIT };
    } else {
      const latest = rows[0];
      headlineByCountry[country] = {
        value: latest.value,
        date: latest.date,
        unit: latest.unit || indicator.unit || "",
      };
    }
  }

  const displayUnit = isIndex ? YOY_UNIT : indicator.unit;

  return (
    <div className="space-y-6">
      <div>
        <Link href="/indicators" className="text-sm text-primary hover:underline">
          Indicators
        </Link>
        <span className="text-sm text-muted-foreground mx-1">/</span>
        <span className="text-sm text-muted-foreground">{indicator.name_de || indicator.name}</span>
      </div>

      <div>
        <h1 className="text-2xl font-bold">{indicator.name_de || indicator.name}</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {indicator.name} &middot; {displayUnit}
        </p>
      </div>

      {indicator.description && (
        <p className="text-sm text-muted-foreground">{indicator.description}</p>
      )}

      <div className="rounded-lg border bg-card max-w-3xl">
        <table className="w-full text-sm">
          <colgroup>
            <col />
            <col className="w-32" />
            <col className="w-32" />
            <col className="w-28" />
          </colgroup>
          <thead>
            <tr className="border-b">
              <th className="text-left py-3 px-4 font-medium text-muted-foreground">Land</th>
              <th className="text-right py-3 pl-4 pr-2 font-medium text-muted-foreground">Wert</th>
              <th className="text-left py-3 pl-2 pr-4 font-medium text-muted-foreground">Einheit</th>
              <th className="text-right py-3 px-4 font-medium text-muted-foreground">Datum</th>
            </tr>
          </thead>
          <tbody>
            {COUNTRIES.filter((c) => headlineByCountry[c.code]).map((c) => {
              const headline = headlineByCountry[c.code]!;
              return (
                <tr key={c.code} className="border-b border-border/50 last:border-0 hover:bg-muted/30">
                  <td className="py-3 px-4">
                    <Link
                      href={`/indicators/${slug}/${c.code.toLowerCase()}`}
                      className="flex items-center gap-2 hover:text-primary"
                    >
                      <span>{c.flag}</span>
                      <span className="font-medium">{c.name_de}</span>
                    </Link>
                  </td>
                  <td className="py-3 pl-4 pr-2 text-right font-mono whitespace-nowrap">
                    {headline.value.toLocaleString("en-US", { maximumFractionDigits: 2 })}
                  </td>
                  <td className="py-3 pl-2 pr-4 text-left text-muted-foreground text-xs whitespace-nowrap">
                    {headline.unit}
                  </td>
                  <td className="py-3 px-4 text-right text-muted-foreground text-xs whitespace-nowrap">
                    {headline.date}
                  </td>
                </tr>
              );
            })}
            {COUNTRIES.filter((c) => headlineByCountry[c.code]).length === 0 && (
              <tr>
                <td colSpan={4} className="py-6 px-4 text-center text-sm text-muted-foreground">
                  Für diesen Indikator liegen aktuell keine Daten vor.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
