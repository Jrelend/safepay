import type { Metadata } from "next";
import { Suspense } from "react";

import { Skeleton } from "@/components/ui";

import { AdminLoginForm } from "./admin-login-form";

export const metadata: Metadata = { title: "Админ нэвтрэх" };

export default function AdminLoginPage() {
  return (
    <Suspense fallback={<Skeleton lines={2} />}>
      <AdminLoginForm />
    </Suspense>
  );
}
