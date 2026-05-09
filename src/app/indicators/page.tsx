import Link from "next/link";
import { getIndicatorCatalog, CATEGORY_META } from "@/lib/indicators";
import {
  TrendingUp,
  Percent,
  Users,
  Landmark,
  ArrowLeftRight,
  Building2,
  Factory,
  ShoppingCart,
  Home,
  Zap,
  Receipt,
  HeartPulse,
  Eye,
} from "lucide-react";

export const revalidate = 3600;

const categoryIcons: Record<string, React.ReactNode> = {
  Overview:   <Eye className="h-5 w-5" />,
  GDP:        <TrendingUp className="h-5 w-5" />,
  Prices:     <Percent className="h-5 w-5" />,
  Labour:     <Users className="h-5 w-5" />,
  Money:      <Landmark className="h-5 w-5" />,
  Trade:      <ArrowLeftRight className="h-5 w-5" />,
  Government: <Building2 className="h-5 w-5" />,
  Business:   <Factory className="h-5 w-5" />,
  Consumer:   <ShoppingCart className="h-5 w-5" />,
  Housing:    <Home className="h-5 w-5" />,
  Energy:     <Zap className="h-5 w-5" />,
  Taxes:      <Receipt className="h-5 w-5" />,
  Health:     <HeartPulse className="h-5 w-5" />,
};

export default async function IndicatorsPage() {
  const catalog = await getIndicatorCatalog({ includeTier3: true });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Indicators</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Browse macroeconomic indicators by category
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {catalog.map((cat) => {
          const firstInd = cat.indicators[0];
          if (!firstInd) return null;
          const meta = CATEGORY_META[cat.name];
          return (
            <Link
              key={cat.slug}
              href={`/indicators/${firstInd.slug}`}
              className="rounded-lg border bg-card p-5 hover:bg-muted/30 transition-colors"
            >
              <div className="flex items-center gap-3 mb-3">
                <div className="text-primary">{categoryIcons[cat.name]}</div>
                <h2 className="font-semibold">{meta?.name_de || cat.name_de}</h2>
              </div>
              <p className="text-xs text-muted-foreground">
                {cat.indicators.length} indicators
              </p>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
