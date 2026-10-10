import type { Metadata, Viewport } from "next";
import { Suspense } from "react";

import { AppHeader } from "@/components/app-header";
import { BottomNav } from "@/components/bottom-nav";
import { SimulationBanner } from "@/components/simulation-banner";
import { SessionProvider } from "@/lib/client/session";
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
        <a
          href="#main"
          className="bg-brand text-brand-foreground sr-only z-50 rounded px-3 py-2 focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
        >
          Үндсэн агуулга руу шилжих
        </a>
        <SessionProvider>
          <SimulationBanner />
          <AppHeader />
          <main id="main" className="mx-auto w-full max-w-md md:max-w-2xl flex-1 px-4 pt-6 pb-28">
            {children}
          </main>
          <footer className="text-muted pb-24 text-center text-xs">{mn.footer}</footer>
          <Suspense fallback={null}>
            <BottomNav />
          </Suspense>
        </SessionProvider>
      </body>
    </html>
  );
}
