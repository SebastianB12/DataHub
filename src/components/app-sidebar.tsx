"use client";

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
} from "@/components/ui/sidebar";
import { ThemeToggle } from "@/components/theme-toggle";
import { INDICATOR_CATEGORIES, COUNTRIES } from "@/lib/indicators";
import {
  LayoutDashboard,
  TrendingUp,
  Percent,
  Users,
  Landmark,
  ArrowLeftRight,
  Building2,
  Globe,
} from "lucide-react";

const categoryIcons: Record<string, React.ReactNode> = {
  "gdp-growth": <TrendingUp className="h-4 w-4" />,
  "inflation-prices": <Percent className="h-4 w-4" />,
  labor: <Users className="h-4 w-4" />,
  monetary: <Landmark className="h-4 w-4" />,
  trade: <ArrowLeftRight className="h-4 w-4" />,
  government: <Building2 className="h-4 w-4" />,
};

export function AppSidebar() {
  const pathname = usePathname();

  return (
    <Sidebar>
      <SidebarHeader className="border-b border-sidebar-border px-4 py-3">
        <Link href="/" className="flex items-center gap-2">
          <div className="text-lg font-bold tracking-tight">EconPulse</div>
        </Link>
        <div className="text-xs text-muted-foreground">Global Economic Data</div>
      </SidebarHeader>

      <SidebarContent>
        {/* Overview */}
        <SidebarGroup>
          <SidebarGroupLabel>Overview</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={pathname === "/"}>
                  <Link href="/">
                    <LayoutDashboard className="h-4 w-4" />
                    Dashboard
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {/* Indicators */}
        <SidebarGroup>
          <SidebarGroupLabel>Indicators</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {INDICATOR_CATEGORIES.map((cat) => (
                <SidebarMenuItem key={cat.slug}>
                  <SidebarMenuButton
                    asChild
                    isActive={pathname.startsWith(`/indicators`) && pathname.includes(cat.indicators[0])}
                  >
                    <Link href={`/indicators/${cat.indicators[0]}/us`}>
                      {categoryIcons[cat.slug]}
                      {cat.name_de}
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {/* Countries */}
        <SidebarGroup>
          <SidebarGroupLabel>Countries</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {COUNTRIES.map((country) => (
                <SidebarMenuItem key={country.code}>
                  <SidebarMenuButton
                    asChild
                    isActive={pathname === `/countries/${country.code.toLowerCase()}`}
                  >
                    <Link href={`/countries/${country.code.toLowerCase()}`}>
                      <Globe className="h-4 w-4" />
                      {country.flag} {country.name_de}
                    </Link>
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
