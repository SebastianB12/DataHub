import Link from "next/link";
import { COUNTRIES } from "@/lib/indicators";

export default function CountriesPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Countries</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Browse economic data by country
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {COUNTRIES.map((c) => (
          <Link
            key={c.code}
            href={`/countries/${c.code.toLowerCase()}`}
            className="rounded-lg border bg-card p-5 hover:bg-muted/30 transition-colors"
          >
            <div className="flex items-center gap-3">
              <span className="text-3xl">{c.flag}</span>
              <div>
                <div className="font-semibold">{c.name_de}</div>
                <div className="text-xs text-muted-foreground">{c.name}</div>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
