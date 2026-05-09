import { createClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

export const supabase = createClient(supabaseUrl, supabaseAnonKey);

/**
 * Fetch all rows from a query, paginating automatically if the result
 * hits the PostgREST max-rows limit. Avoids silent data truncation.
 */
export async function fetchAll<T = Record<string, unknown>>(
  table: string,
  select: string,
  filters: Record<string, string>,
  orderBy: { column: string; ascending: boolean } = { column: "date", ascending: true },
): Promise<T[]> {
  const PAGE_SIZE = 1000;
  const all: T[] = [];
  let offset = 0;

  while (true) {
    let query = supabase.from(table).select(select);
    for (const [key, value] of Object.entries(filters)) {
      query = query.eq(key, value);
    }
    query = query.order(orderBy.column, { ascending: orderBy.ascending })
      .range(offset, offset + PAGE_SIZE - 1);

    const { data, error } = await query;
    if (error || !data) break;

    all.push(...(data as T[]));
    if (data.length < PAGE_SIZE) break; // last page
    offset += PAGE_SIZE;
  }

  return all;
}
