import type { Metadata } from "next";
import { Suspense } from "react";

import { Skeleton } from "@/components/ui";

import { InviteView } from "./invite-view";

export const metadata: Metadata = { title: "Гэрээний урилга", referrer: "no-referrer" };

export default function InvitePage() {
  return (
    <Suspense fallback={<Skeleton />}>
      <InviteView />
    </Suspense>
  );
}
