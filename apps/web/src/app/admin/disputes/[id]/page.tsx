import type { Metadata } from "next";
import { Suspense } from "react";

import { Skeleton } from "@/components/ui";

import { AdminDisputeView } from "./admin-dispute";

export const metadata: Metadata = { title: "Маргаан шийдвэрлэх" };

export default function AdminDisputePage() {
  return (
    <Suspense fallback={<Skeleton />}>
      <AdminDisputeView />
    </Suspense>
  );
}
