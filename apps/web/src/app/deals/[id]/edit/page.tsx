import type { Metadata } from "next";
import { Suspense } from "react";

import { Skeleton } from "@/components/ui";

import { EditDraft } from "./edit-draft";

export const metadata: Metadata = { title: "Нөхцөл засах" };

export default function EditDealPage() {
  return (
    <Suspense fallback={<Skeleton />}>
      <EditDraft />
    </Suspense>
  );
}
