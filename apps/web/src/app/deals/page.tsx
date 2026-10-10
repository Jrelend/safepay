import type { Metadata } from "next";
import { Suspense } from "react";

import { Skeleton } from "@/components/ui";

import { DealHistory } from "./deal-history";

export const metadata: Metadata = { title: "Миний гэрээнүүд" };

export default function DealsPage() {
  return (
    <Suspense fallback={<Skeleton />}>
      <DealHistory />
    </Suspense>
  );
}
