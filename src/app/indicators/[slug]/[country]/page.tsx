import { supabase } from "@/lib/supabase";
import { notFound } from "next/navigation";
import { detectFrequency } from "@/lib/transforms";
import { IndicatorDetail } from "./indicator-detail";

export const revalidate = 3600; // ISR: 1 hour

interface Props {
  params: Promise<{ slug: string; country: string }>;
}

interface RawDataPoint {
  date: string;
  value: number;
  source: string;
  unit: string | null;
  series_id: string | null;
  adjustment: string | null;
}

export interface VariantData {
  source: string;       // e.g. "destatis", "eurostat", "fred"
  adjustment: string;   // "SA" | "NSA" | ""
  frequency: "M" | "Q" | "A";
  seriesId: string;
  unit: string;
  data: { date: string; value: number }[];
}

async function getIndicatorData(slug: string, countryCode: string) {
  const code = countryCode.toUpperCase();

  const [indicatorRes, countryRes, defaultSourceRes, rawRes, relatedRes] = await Promise.all([
    supabase.from("indicators").select("*").eq("slug", slug).single(),
    supabase.from("countries").select("*").eq("code", code).single(),
    // Default source for this (indicator, country) — drives initial UI selection
    supabase
      .from("indicator_sources")
      .select("source")
      .eq("indicator", slug)
      .eq("country", code)
      .eq("is_default", true)
      .limit(1)
      .maybeSingle(),
    // All raw data points across every (source, adjustment) combination
    supabase
      .from("data_points")
      .select("date, value, source, unit, series_id, adjustment")
      .eq("indicator", slug)
      .eq("country", code)
      .order("date", { ascending: true }),
    // Related: same category, tier<=2, excluding self
    (async () => {
      const self = await supabase.from("indicators").select("category").eq("slug", slug).single();
      if (!self.data?.category) return { data: [] as { slug: string; name: string; name_de: string }[] };
      return supabase
        .from("indicators")
        .select("slug, name, name_de")
        .eq("category", self.data.category)
        .lte("tier", 2)
        .neq("slug", slug)
        .order("tier")
        .limit(8);
    })(),
  ]);

  if (indicatorRes.error || !indicatorRes.data) return null;
  if (countryRes.error || !countryRes.data) return null;

  const raw = (rawRes.data || []) as RawDataPoint[];
  const defaultSource = defaultSourceRes.data?.source ?? "";

  // Group raw data by (source, adjustment) → one variant per combination
  const bySourceAdj = new Map<string, RawDataPoint[]>();
  for (const row of raw) {
    const key = `${row.source}:${row.adjustment || ""}`;
    if (!bySourceAdj.has(key)) bySourceAdj.set(key, []);
    bySourceAdj.get(key)!.push(row);
  }

  // Default source first, then alphabetical
  const sortedKeys = [...bySourceAdj.keys()].sort((a, b) => {
    const sa = a.split(":")[0];
    const sb = b.split(":")[0];
    if (sa === defaultSource && sb !== defaultSource) return -1;
    if (sb === defaultSource && sa !== defaultSource) return 1;
    return a.localeCompare(b);
  });

  const variants: VariantData[] = sortedKeys.map((key) => {
    const rows = bySourceAdj.get(key)!;
    const [source, adjustment] = key.split(":");
    const last = rows[rows.length - 1];
    const data = rows.map((d) => ({ date: d.date, value: d.value }));
    return {
      source,
      adjustment,
      frequency: detectFrequency(data) || "M",
      seriesId: last?.series_id || "",
      unit: last?.unit || "",
      data,
    };
  });

  return {
    indicator: indicatorRes.data,
    country: countryRes.data,
    variants,
    defaultSource,
    relatedIndicators: (relatedRes.data || []) as { slug: string; name: string; name_de: string }[],
  };
}

export default async function IndicatorPage({ params }: Props) {
  const { slug, country } = await params;
  const data = await getIndicatorData(slug, country);

  if (!data) notFound();

  const { indicator, country: countryData, variants, defaultSource, relatedIndicators } = data;

  if (variants.length === 0) {
    notFound();
  }

  // Default variant: pick a row whose source matches indicator_sources.is_default;
  // among those prefer SA, then NSA, then any. Fallback to first variant if no default
  // row exists (e.g. data exists but no indicator_sources entry yet).
  const defaultSourceVariants = variants.filter((v) => v.source === defaultSource);
  const defaultVariant =
    defaultSourceVariants.find((v) => v.adjustment === "SA") ||
    defaultSourceVariants.find((v) => v.adjustment === "NSA") ||
    defaultSourceVariants[0] ||
    variants.find((v) => v.adjustment === "SA") ||
    variants.find((v) => v.adjustment === "NSA") ||
    variants[0];

  return (
    <IndicatorDetail
      indicator={indicator}
      country={countryData}
      countryCode={country}
      variants={variants}
      defaultSource={defaultVariant.source}
      defaultAdjustment={defaultVariant.adjustment}
      defaultDisplay={(indicator.default_display as "raw" | "pop" | "yoy" | undefined) || "raw"}
      relatedIndicators={relatedIndicators}
    />
  );
}
