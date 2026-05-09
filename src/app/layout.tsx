import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { ThemeProvider } from "@/components/theme-provider";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/app-sidebar";
import { SearchPalette } from "@/components/search-palette";
import { getIndicatorCatalog } from "@/lib/indicators";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "EconPulse — Global Economic Data",
  description:
    "Free macroeconomic data with full history. GDP, inflation, unemployment, interest rates and more.",
};

export const revalidate = 3600; // catalog is slow-moving

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const catalog = await getIndicatorCatalog();

  return (
    <html
      lang="en"
      className={`${inter.className} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full bg-background text-foreground">
        <ThemeProvider>
          <SidebarProvider>
            <AppSidebar catalog={catalog} />
            <main className="flex-1 overflow-auto">
              <div className="flex items-center gap-3 border-b px-4 py-2">
                <SidebarTrigger />
                <div className="flex-1 flex justify-end">
                  <SearchPalette catalog={catalog} />
                </div>
              </div>
              <div className="p-6">{children}</div>
            </main>
          </SidebarProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
