import { supabase } from "./supabase";

export interface IndicatorEntry {
  slug: string;
  name: string;
  name_de: string;
  tier?: number;
  unit?: string;
  unit_type?: string;
  frequency?: string;
  te_slug?: string;
}

export interface IndicatorCategory {
  slug: string;      // stable key for URL/state (lowercased category, e.g. "prices")
  name: string;      // display name (English, == DB category)
  name_de: string;   // German label
  indicators: IndicatorEntry[];
}

/**
 * Indicators whose raw stored value is an index (e.g., CPI 2020=100)
 * but should be displayed as % YoY in overviews. The detail page still
 * offers an Index/YoY toggle; this list only affects headline displays.
 */
export const INDEX_INDICATORS = new Set<string>([
  "inflation-cpi",
  "core-cpi",
  "ppi",
]);

export const YOY_UNIT = "% YoY";

// TE-aligned category order + German labels. When a new category appears in
// the DB (e.g. "Energy" after the EIA provider lands), add it here to give it
// a German label and a slot in the ordering — otherwise it falls through to
// "Other" at the end.
export const CATEGORY_META: Record<string, { name_de: string; order: number }> = {
  GDP:        { name_de: "BIP & Wachstum",       order: 1 },
  Prices:     { name_de: "Inflation & Preise",   order: 2 },
  Labour:     { name_de: "Arbeitsmarkt",         order: 3 },
  Money:      { name_de: "Geldpolitik",          order: 4 },
  Trade:      { name_de: "Außenhandel",          order: 5 },
  Government: { name_de: "Staatsfinanzen",       order: 6 },
  Business:   { name_de: "Wirtschaft",           order: 7 },
  Consumer:   { name_de: "Konsum",               order: 8 },
  Housing:    { name_de: "Immobilien",           order: 9 },
  Energy:     { name_de: "Energie",              order: 10 },
  Taxes:      { name_de: "Steuern",              order: 11 },
  Health:     { name_de: "Gesundheit",           order: 12 },
  Overview:   { name_de: "Überblick",            order: 0 },
};

function categorySlug(category: string): string {
  return category.toLowerCase();
}

/**
 * Fetch the indicator catalog from the DB, grouped by category.
 * Used server-side in the root layout to hydrate sidebar + search palette.
 * Returns only tier<=2 by default; pass {includeTier3: true} for full list.
 */
export async function getIndicatorCatalog(
  opts: { includeTier3?: boolean } = {},
): Promise<IndicatorCategory[]> {
  const maxTier = opts.includeTier3 ? 3 : 2;
  const { data, error } = await supabase
    .from("indicators")
    .select("slug, name, name_de, category, tier, unit, unit_type, frequency, te_slug")
    .lte("tier", maxTier)
    .order("category")
    .order("tier")
    .order("name");

  if (error || !data) {
    console.error("[indicators] catalog fetch failed:", error);
    return [];
  }

  const byCategory = new Map<string, IndicatorEntry[]>();
  for (const row of data as Array<{
    slug: string; name: string; name_de: string | null; category: string;
    tier: number | null; unit: string | null; unit_type: string | null;
    frequency: string | null; te_slug: string | null;
  }>) {
    const cat = row.category || "Other";
    if (!byCategory.has(cat)) byCategory.set(cat, []);
    byCategory.get(cat)!.push({
      slug: row.slug,
      name: row.name,
      name_de: row.name_de || row.name,
      tier: row.tier ?? 3,
      unit: row.unit || undefined,
      unit_type: row.unit_type || undefined,
      frequency: row.frequency || undefined,
      te_slug: row.te_slug || undefined,
    });
  }

  const categories: IndicatorCategory[] = [];
  for (const [cat, indicators] of byCategory.entries()) {
    const meta = CATEGORY_META[cat];
    categories.push({
      slug: categorySlug(cat),
      name: cat,
      name_de: meta?.name_de || cat,
      indicators,
    });
  }
  categories.sort((a, b) => {
    const oa = CATEGORY_META[a.name]?.order ?? 99;
    const ob = CATEGORY_META[b.name]?.order ?? 99;
    return oa - ob;
  });
  return categories;
}

export const COUNTRIES = [
  { code: "US", name: "United States", name_de: "USA", flag: "\u{1F1FA}\u{1F1F8}" },
  { code: "EA", name: "Euro Area", name_de: "Euro-Raum", flag: "\u{1F1EA}\u{1F1FA}" },
  { code: "GB", name: "United Kingdom", name_de: "UK", flag: "\u{1F1EC}\u{1F1E7}" },
  { code: "DE", name: "Germany", name_de: "Deutschland", flag: "\u{1F1E9}\u{1F1EA}" },
  { code: "CN", name: "China", name_de: "China", flag: "\u{1F1E8}\u{1F1F3}" },
  { code: "FR", name: "France", name_de: "Frankreich", flag: "\u{1F1EB}\u{1F1F7}" },
] as const;
