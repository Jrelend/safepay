import type { Metadata } from "next";

import { ForgotPasswordForm } from "./forgot-form";

export const metadata: Metadata = { title: "Нууц үг сэргээх" };

export default function ForgotPasswordPage() {
  return <ForgotPasswordForm />;
}
