"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
} from "@/components/ui/sidebar";
import { ThemeToggle } from "@/components/theme-toggle";
import { COUNTRIES, type IndicatorCategory } from "@/lib/indicators";
import {
  LayoutDashboard,
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
  Globe,
  ChevronRight,
  Eye,
} from "lucide-react";

const categoryIcons: Record<string, React.ReactNode> = {
  Overview:   <Eye className="h-4 w-4" />,
  GDP:        <TrendingUp className="h-4 w-4" />,
  Prices:     <Percent className="h-4 w-4" />,
  Labour:     <Users className="h-4 w-4" />,
  Money:      <Landmark className="h-4 w-4" />,
  Trade:      <ArrowLeftRight className="h-4 w-4" />,
  Government: <Building2 className="h-4 w-4" />,
  Business:   <Factory className="h-4 w-4" />,
  Consumer:   <ShoppingCart className="h-4 w-4" />,
  Housing:    <Home className="h-4 w-4" />,
  Energy:     <Zap className="h-4 w-4" />,
  Taxes:      <Receipt className="h-4 w-4" />,
  Health:     <HeartPulse className="h-4 w-4" />,
};

export function AppSidebar({ catalog }: { catalog: IndicatorCategory[] }) {
  const pathname = usePathname();

  const activeCategory = catalog.find((cat) =>
    cat.indicators.some((ind) => pathname.includes(`/indicators/${ind.slug}`))
  );

  const [openCategories, setOpenCategories] = useState<Set<string>>(() => {
    const initial = new Set<string>();
    if (activeCategory) initial.add(activeCategory.slug);
    return initial;
  });

  function toggleCategory(slug: string) {
    setOpenCategories((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  }

  return (
    <Sidebar>
      <SidebarHeader className="border-b border-sidebar-border px-4 py-3">
        <Link href="/" className="flex items-center gap-2">
          <div className="text-lg font-bold tracking-tight">EconPulse</div>
        </Link>
        <div className="flex items-center justify-between">
          <div className="text-xs text-muted-foreground">Global Economic Data</div>
          <ThemeToggle />
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Overview</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton render={<Link href="/" />} isActive={pathname === "/"}>
                  <LayoutDashboard className="h-4 w-4" />
                  Dashboard
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel>Indicators</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {catalog.map((cat) => {
                const isOpen = openCategories.has(cat.slug);
                const isCatActive = activeCategory?.slug === cat.slug;

                return (
                  <SidebarMenuItem key={cat.slug}>
                    <SidebarMenuButton
                      onClick={() => toggleCategory(cat.slug)}
                      isActive={isCatActive && !isOpen}
                      className="cursor-pointer"
                    >
                      {categoryIcons[cat.name] || <ChevronRight className="h-4 w-4" />}
                      <span className="flex-1 truncate">{cat.name_de}</span>
                      <span className="text-[10px] text-muted-foreground tabular-nums mr-1 shrink-0">
                        {cat.indicators.length}
                      </span>
                      <ChevronRight
                        className={`h-3.5 w-3.5 text-muted-foreground transition-transform duration-200 ${
                          isOpen ? "rotate-90" : ""
                        }`}
                      />
                    </SidebarMenuButton>

                    {isOpen && (
                      <SidebarMenuSub>
                        {cat.indicators.map((ind) => {
                          const isIndActive = pathname.includes(`/indicators/${ind.slug}`);
                          return (
                            <SidebarMenuSubItem key={ind.slug}>
                              <SidebarMenuSubButton
                                render={<Link href={`/indicators/${ind.slug}`} />}
                                isActive={isIndActive}
                                title={ind.name_de}
                              >
                                <span className="truncate">{ind.name_de}</span>
                              </SidebarMenuSubButton>
                            </SidebarMenuSubItem>
                          );
                        })}
                      </SidebarMenuSub>
                    )}
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel>Countries</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {COUNTRIES.map((country) => (
                <SidebarMenuItem key={country.code}>
                  <SidebarMenuButton
                    render={<Link href={`/countries/${country.code.toLowerCase()}`} />}
                    isActive={pathname === `/countries/${country.code.toLowerCase()}`}
                  >
                    <Globe className="h-4 w-4" />
                    <span className="truncate">{country.flag} {country.name_de}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  );
}
