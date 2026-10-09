import type { Metadata, Viewport } from "next";

import { AppHeader } from "@/components/app-header";
import { BottomNav } from "@/components/bottom-nav";
import { SimulationBanner } from "@/components/simulation-banner";
import { mn } from "@/lib/i18n/mn";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: `${mn.appName} — ${mn.tagline}`, template: `%s · ${mn.appName}` },
  description: mn.hero.body,
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#161b22" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="mn" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <SimulationBanner />
        <AppHeader />
        <main className="mx-auto w-full max-w-md flex-1 px-4 pt-6 pb-28">{children}</main>
        <footer className="text-muted pb-20 text-center text-xs">{mn.footer}</footer>
        <BottomNav />
      </body>
    </html>
  );
}
