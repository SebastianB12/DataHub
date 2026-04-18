import { supabase } from "@/lib/supabase";
import { notFound } from "next/navigation";
import { IndicatorDetail } from "./indicator-detail";

export const revalidate = 3600; // ISR: 1 hour

interface Props {
  params: Promise<{ slug: string; country: string }>;
}

async function getIndicatorData(slug: string, countryCode: string) {
  const [indicatorRes, dataRes, countryRes] = await Promise.all([
    supabase.from("indicators").select("*").eq("slug", slug).single(),
    supabase
      .from("data_points")
      .select("date, value")
      .eq("indicator", slug)
      .eq("country", countryCode.toUpperCase())
      .order("date", { ascending: true }),
    supabase
      .from("countries")
      .select("*")
      .eq("code", countryCode.toUpperCase())
      .single(),
  ]);

  if (indicatorRes.error || !indicatorRes.data) return null;
  if (countryRes.error || !countryRes.data) return null;

  return {
    indicator: indicatorRes.data,
    country: countryRes.data,
    dataPoints: dataRes.data || [],
  };
}

export default async function IndicatorPage({ params }: Props) {
  const { slug, country } = await params;
  const data = await getIndicatorData(slug, country);

  if (!data) notFound();

  const { indicator, country: countryData, dataPoints } = data;

  // Compute stats
  const values = dataPoints.map((d: { value: number }) => d.value);
  const latest = dataPoints[dataPoints.length - 1];
  const previous = dataPoints[dataPoints.length - 2];
  const allTimeHigh = Math.max(...values);
  const allTimeLow = Math.min(...values);
  const earliest = dataPoints[0];

  const change =
    latest && previous
      ? ((latest.value - previous.value) / Math.abs(previous.value)) * 100
      : 0;

  return (
    <IndicatorDetail
      indicator={indicator}
      country={countryData}
      dataPoints={dataPoints}
      stats={{
        current: latest?.value ?? 0,
        previous: previous?.value ?? 0,
        change: Math.round(change * 100) / 100,
        allTimeHigh,
        allTimeLow,
        earliestDate: earliest?.date ?? "",
        latestDate: latest?.date ?? "",
      }}
    />
  );
}
