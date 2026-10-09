import type { Metadata } from "next";
import { Suspense } from "react";

import { Skeleton } from "@/components/ui";

import { VerifyEmail } from "./verify-email";

export const metadata: Metadata = { title: "Имэйл баталгаажуулах" };

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<Skeleton lines={1} />}>
      <VerifyEmail />
    </Suspense>
  );
}
