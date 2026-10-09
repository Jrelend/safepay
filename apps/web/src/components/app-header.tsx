import Link from "next/link";

import { mn } from "@/lib/i18n/mn";

export function AppHeader() {
  return (
    <header className="bg-surface border-border sticky top-0 z-10 border-b">
      <div className="mx-auto flex h-14 max-w-md items-center justify-between px-4">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <span
            aria-hidden
            className="bg-brand text-brand-foreground grid size-8 place-items-center rounded-lg text-sm font-bold"
          >
            SP
          </span>
          <span>{mn.appName}</span>
        </Link>
        <span className="border-border text-muted rounded-full border px-2 py-0.5 text-[11px] font-medium">
          Beta v0.1
        </span>
      </div>
    </header>
  );
}
