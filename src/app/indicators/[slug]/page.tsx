import { supabase } from "@/lib/supabase";
import { notFound } from "next/navigation";
import Link from "next/link";
import { COUNTRIES } from "@/lib/indicators";

export const revalidate = 3600;

interface Props {
  params: Promise<{ slug: string }>;
}

export default async function IndicatorOverviewPage({ params }: Props) {
  const { slug } = await params;

  const [indicatorRes, dataRes] = await Promise.all([
    supabase.from("indicators").select("*").eq("slug", slug).single(),
    supabase
      .from("data_points")
      .select("country, date, value")
      .eq("indicator", slug)
      .order("date", { ascending: false }),
  ]);

  if (indicatorRes.error || !indicatorRes.data) notFound();

  const indicator = indicatorRes.data;

  // Get latest value per country
  const latestByCountry: Record<string, { value: number; date: string }> = {};
  for (const row of dataRes.data || []) {
    if (!latestByCountry[row.country]) {
      latestByCountry[row.country] = { value: row.value, date: row.date };
    }
  }

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
          {indicator.name} &middot; {indicator.unit}
        </p>
      </div>

      {indicator.description && (
        <p className="text-sm text-muted-foreground">{indicator.description}</p>
      )}

      <div className="rounded-lg border bg-card">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b">
              <th className="text-left py-3 px-4 font-medium text-muted-foreground">Country</th>
              <th className="text-right py-3 px-4 font-medium text-muted-foreground">Latest Value</th>
              <th className="text-right py-3 px-4 font-medium text-muted-foreground">Date</th>
            </tr>
          </thead>
          <tbody>
            {COUNTRIES.map((c) => {
              const data = latestByCountry[c.code];
              return (
                <tr key={c.code} className="border-b border-border/50 hover:bg-muted/30">
                  <td className="py-3 px-4">
                    <Link
                      href={`/indicators/${slug}/${c.code.toLowerCase()}`}
                      className="flex items-center gap-2 hover:text-primary"
                    >
                      <span>{c.flag}</span>
                      <span className="font-medium">{c.name_de}</span>
                    </Link>
                  </td>
                  <td className="py-3 px-4 text-right font-mono">
                    {data ? data.value.toLocaleString("en-US", { maximumFractionDigits: 2 }) : "—"}
                  </td>
                  <td className="py-3 px-4 text-right text-muted-foreground">
                    {data?.date || "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
