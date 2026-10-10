import type { Metadata } from "next";
import { Suspense } from "react";

import { Skeleton } from "@/components/ui";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Нэвтрэх" };

export default function LoginPage() {
  return (
    <Suspense fallback={<Skeleton lines={2} />}>
      <LoginForm />
    </Suspense>
  );
}
