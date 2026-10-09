import type { Metadata } from "next";
import { Suspense } from "react";

import { Skeleton } from "@/components/ui";

import { DealDetail } from "./deal-detail";

export const metadata: Metadata = { title: "Гэрээний дэлгэрэнгүй" };

export default function DealPage() {
  return (
    <Suspense fallback={<Skeleton lines={4} />}>
      <DealDetail />
    </Suspense>
  );
}
