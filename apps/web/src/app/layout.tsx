import type { Metadata, Viewport } from "next";
import { Suspense } from "react";

import { AppHeader } from "@/components/app-header";
import { BottomNav } from "@/components/bottom-nav";
import { SimulationBanner } from "@/components/simulation-banner";
import { SessionProvider } from "@/lib/client/session";
import { THEME_BOOTSTRAP } from "@/lib/client/theme";
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
    { media: "(prefers-color-scheme: light)", color: "#101d35" },
    { media: "(prefers-color-scheme: dark)", color: "#0b1220" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // suppressHydrationWarning: THEME_BOOTSTRAP may set data-theme before React hydrates.
    <html lang="mn" className="h-full antialiased" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body className="flex min-h-full flex-col">
        <a
          href="#main"
          className="bg-primary text-primary-foreground sr-only z-50 rounded-lg px-3 py-2 focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
        >
          Үндсэн агуулга руу шилжих
        </a>
        <SessionProvider>
          <SimulationBanner />
          <AppHeader />
          <main id="main" className="mx-auto w-full max-w-5xl flex-1 px-4 pt-6 pb-10 sm:px-6 md:pt-8 md:pb-12">
            {children}
          </main>
          <footer className="text-muted border-border border-t px-4 pt-4 pb-28 text-center text-xs md:pb-6">
            {mn.footer}
          </footer>
          <Suspense fallback={null}>
            <BottomNav />
          </Suspense>
        </SessionProvider>
      </body>
    </html>
  );
}
