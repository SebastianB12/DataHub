import { supabase } from "@/lib/supabase";
import Link from "next/link";

export const revalidate = 1800; // ISR: 30 min

async function getLatestValues() {
  const indicators = ["gdp", "inflation-cpi", "interest-rate", "unemployment"];

  const { data } = await supabase
    .from("data_points")
    .select("indicator, country, date, value")
    .eq("country", "US")
    .in("indicator", indicators)
    .order("date", { ascending: false });

  // Get latest value per indicator
  const latest: Record<string, { value: number; date: string }> = {};
  for (const row of data || []) {
    if (!latest[row.indicator]) {
      latest[row.indicator] = { value: row.value, date: row.date };
    }
  }
  return latest;
}

export default async function Dashboard() {
  const latest = await getLatestValues();

  const cards = [
    { label: "US GDP", slug: "gdp", value: latest.gdp?.value, unit: "$B", date: latest.gdp?.date },
    { label: "US Inflation", slug: "inflation-cpi", value: latest["inflation-cpi"]?.value, unit: "%", date: latest["inflation-cpi"]?.date },
    { label: "Fed Funds Rate", slug: "interest-rate", value: latest["interest-rate"]?.value, unit: "%", date: latest["interest-rate"]?.date },
    { label: "US Unemployment", slug: "unemployment", value: latest.unemployment?.value, unit: "%", date: latest.unemployment?.date },
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
        {cards.map((card) => (
          <Link
            key={card.slug}
            href={`/indicators/${card.slug}/us`}
            className="rounded-lg border bg-card p-4 hover:bg-muted/30 transition-colors"
          >
            <div className="text-xs text-muted-foreground uppercase tracking-wide">
              {card.label}
            </div>
            <div className="text-2xl font-bold mt-2">
              {card.value != null
                ? card.unit === "$B"
                  ? `$${card.value.toLocaleString("en-US", { maximumFractionDigits: 1 })}B`
                  : `${card.value.toFixed(2)}${card.unit}`
                : "\u2014"}
            </div>
            <div className="text-xs text-muted-foreground mt-1">{card.date}</div>
          </Link>
        ))}
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
              href={`/indicators/${item.slug}/us`}
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
