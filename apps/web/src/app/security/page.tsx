import type { Metadata } from "next";

import { Security } from "./security";

export const metadata: Metadata = { title: "Аюулгүй байдал" };

export default function SecurityPage() {
  return <Security />;
}
