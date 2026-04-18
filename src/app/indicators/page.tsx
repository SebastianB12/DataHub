import Link from "next/link";
import { INDICATOR_CATEGORIES } from "@/lib/indicators";
import {
  TrendingUp,
  Percent,
  Users,
  Landmark,
  ArrowLeftRight,
  Building2,
} from "lucide-react";

const categoryIcons: Record<string, React.ReactNode> = {
  "gdp-growth": <TrendingUp className="h-5 w-5" />,
  "inflation-prices": <Percent className="h-5 w-5" />,
  labor: <Users className="h-5 w-5" />,
  monetary: <Landmark className="h-5 w-5" />,
  trade: <ArrowLeftRight className="h-5 w-5" />,
  government: <Building2 className="h-5 w-5" />,
};

export default function IndicatorsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Indicators</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Browse macroeconomic indicators by category
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {INDICATOR_CATEGORIES.map((cat) => (
          <Link
            key={cat.slug}
            href={`/indicators/${cat.indicators[0]}/us`}
            className="rounded-lg border bg-card p-5 hover:bg-muted/30 transition-colors"
          >
            <div className="flex items-center gap-3 mb-3">
              <div className="text-primary">{categoryIcons[cat.slug]}</div>
              <h2 className="font-semibold">{cat.name_de}</h2>
            </div>
            <p className="text-xs text-muted-foreground">
              {cat.indicators.length} indicators
            </p>
          </Link>
        ))}
      </div>
    </div>
  );
}
