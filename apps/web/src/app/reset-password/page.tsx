import type { Metadata } from "next";
import { Suspense } from "react";

import { Skeleton } from "@/components/ui";

import { ResetPasswordForm } from "./reset-form";

export const metadata: Metadata = { title: "Шинэ нууц үг" };

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<Skeleton lines={2} />}>
      <ResetPasswordForm />
    </Suspense>
  );
}
