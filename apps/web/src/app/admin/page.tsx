import type { Metadata } from "next";

import { AdminHome } from "./admin-home";

export const metadata: Metadata = { title: "Админ" };

export default function AdminPage() {
  return <AdminHome />;
}
