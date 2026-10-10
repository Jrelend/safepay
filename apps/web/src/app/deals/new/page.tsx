import type { Metadata } from "next";

import { NewDealForm } from "./new-deal-form";

export const metadata: Metadata = { title: "Шинэ гэрээ" };

export default function NewDealPage() {
  return <NewDealForm />;
}
