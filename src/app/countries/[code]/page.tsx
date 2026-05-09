import { supabase } from "@/lib/supabase";
import { notFound } from "next/navigation";
import Link from "next/link";
import { getIndicatorCatalog, INDEX_INDICATORS, YOY_UNIT } from "@/lib/indicators";
import { latestYoY } from "@/lib/transforms";

export const revalidate = 3600;

interface Props {
  params: Promise<{ code: string }>;
}

interface MergedRow {
  indicator: string;
  date: string;
  value: number;
  unit: string | null;
}

export default async function CountryPage({ params }: Props) {
  const { code } = await params;
  const countryCode = code.toUpperCase();

  const [countryRes, dataRes, indicatorsRes, catalog] = await Promise.all([
    supabase.from("countries").select("*").eq("code", countryCode).single(),
    supabase
      .from("data_points_merged")
      .select("indicator, date, value, unit")
      .eq("country", countryCode)
      .order("date", { ascending: false }),
    supabase.from("indicators").select("*"),
    getIndicatorCatalog({ includeTier3: true }),
  ]);

  if (countryRes.error || !countryRes.data) notFound();

  const country = countryRes.data;
  const indicators = indicatorsRes.data || [];
  const rows = (dataRes.data || []) as MergedRow[];

  // Group rows by indicator (already date-desc ordered)
  const rowsByIndicator: Record<string, MergedRow[]> = {};
  for (const row of rows) {
    if (!rowsByIndicator[row.indicator]) rowsByIndicator[row.indicator] = [];
    rowsByIndicator[row.indicator].push(row);
  }

  // Per indicator: headline { value, date, unit } — YoY for index indicators, else latest raw value
  const headlineByIndicator: Record<string, { value: number; date: string; unit: string }> = {};
  for (const [indicator, indRows] of Object.entries(rowsByIndicator)) {
    if (INDEX_INDICATORS.has(indicator)) {
      const asc = [...indRows].reverse().map((r) => ({ date: r.date, value: r.value }));
      const yoy = latestYoY(asc);
      if (yoy) {
        headlineByIndicator[indicator] = { value: yoy.value, date: yoy.date, unit: YOY_UNIT };
      }
    } else {
      const latest = indRows[0];
      headlineByIndicator[indicator] = {
        value: latest.value,
        date: latest.date,
        unit: latest.unit || "",
      };
    }
  }

  const indicatorMap: Record<string, { name: string; name_de: string }> = {};
  for (const ind of indicators) {
    indicatorMap[ind.slug] = { name: ind.name, name_de: ind.name_de };
  }

  return (
    <div className="space-y-6">
      <div>
        <Link href="/countries" className="text-sm text-primary hover:underline">
          Countries
        </Link>
        <span className="text-sm text-muted-foreground mx-1">/</span>
        <span className="text-sm text-muted-foreground">{country.name_de || country.name}</span>
      </div>

      <div className="flex items-center gap-3">
        <span className="text-3xl">{country.flag_emoji}</span>
        <div>
          <h1 className="text-2xl font-bold">{country.name_de || country.name}</h1>
          <p className="text-sm text-muted-foreground">{country.name} &middot; {country.region}</p>
        </div>
      </div>

      {catalog.map((cat) => {
        const catIndicators = cat.indicators.filter((ind) => headlineByIndicator[ind.slug]);
        if (catIndicators.length === 0) return null;

        return (
          <div key={cat.slug} className="space-y-2 max-w-3xl">
            <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
              {cat.name_de}
            </h2>
            <div className="rounded-lg border bg-card">
              <table className="w-full text-sm">
                <colgroup>
                  <col />
                  <col className="w-32" />
                  <col className="w-32" />
                  <col className="w-28" />
                </colgroup>
                <tbody>
                  {catIndicators.map((entry) => {
                    const headline = headlineByIndicator[entry.slug];
                    const ind = indicatorMap[entry.slug];
                    if (!headline || !ind) return null;
                    return (
                      <tr key={entry.slug} className="border-b border-border/50 last:border-0 hover:bg-muted/30">
                        <td className="py-3 px-4">
                          <Link
                            href={`/indicators/${entry.slug}/${code}`}
                            className="hover:text-primary font-medium"
                          >
                            {ind.name_de || ind.name}
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
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}
