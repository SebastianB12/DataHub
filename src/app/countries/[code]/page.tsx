import { supabase } from "@/lib/supabase";
import { notFound } from "next/navigation";
import Link from "next/link";
import { INDICATOR_CATEGORIES } from "@/lib/indicators";

export const revalidate = 3600;

interface Props {
  params: Promise<{ code: string }>;
}

export default async function CountryPage({ params }: Props) {
  const { code } = await params;
  const countryCode = code.toUpperCase();

  const [countryRes, dataRes, indicatorsRes] = await Promise.all([
    supabase.from("countries").select("*").eq("code", countryCode).single(),
    supabase
      .from("data_points")
      .select("indicator, date, value")
      .eq("country", countryCode)
      .order("date", { ascending: false }),
    supabase.from("indicators").select("*"),
  ]);

  if (countryRes.error || !countryRes.data) notFound();

  const country = countryRes.data;
  const indicators = indicatorsRes.data || [];

  // Get latest value per indicator
  const latestByIndicator: Record<string, { value: number; date: string }> = {};
  for (const row of dataRes.data || []) {
    if (!latestByIndicator[row.indicator]) {
      latestByIndicator[row.indicator] = { value: row.value, date: row.date };
    }
  }

  // Build indicator lookup
  const indicatorMap: Record<string, { name: string; name_de: string; unit: string }> = {};
  for (const ind of indicators) {
    indicatorMap[ind.slug] = { name: ind.name, name_de: ind.name_de, unit: ind.unit };
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

      {INDICATOR_CATEGORIES.map((cat) => {
        const catIndicators = cat.indicators.filter(
          (slug) => latestByIndicator[slug]
        );
        if (catIndicators.length === 0) return null;

        return (
          <div key={cat.slug} className="space-y-2">
            <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
              {cat.name_de}
            </h2>
            <div className="rounded-lg border bg-card">
              <table className="w-full text-sm">
                <tbody>
                  {catIndicators.map((slug) => {
                    const data = latestByIndicator[slug];
                    const ind = indicatorMap[slug];
                    if (!data || !ind) return null;
                    return (
                      <tr key={slug} className="border-b border-border/50 last:border-0 hover:bg-muted/30">
                        <td className="py-3 px-4">
                          <Link
                            href={`/indicators/${slug}/${code}`}
                            className="hover:text-primary font-medium"
                          >
                            {ind.name_de || ind.name}
                          </Link>
                        </td>
                        <td className="py-3 px-4 text-right font-mono">
                          {data.value.toLocaleString("en-US", { maximumFractionDigits: 2 })}
                          <span className="text-muted-foreground ml-1 text-xs">{ind.unit}</span>
                        </td>
                        <td className="py-3 px-4 text-right text-muted-foreground text-xs">
                          {data.date}
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
