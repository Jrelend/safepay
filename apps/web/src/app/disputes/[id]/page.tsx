import type { Metadata } from "next";
import { Suspense } from "react";

import { Skeleton } from "@/components/ui";

import { DisputeDetail } from "./dispute-detail";

export const metadata: Metadata = { title: "Маргаан" };

export default function DisputePage() {
  return (
    <Suspense fallback={<Skeleton />}>
      <DisputeDetail />
    </Suspense>
  );
}
