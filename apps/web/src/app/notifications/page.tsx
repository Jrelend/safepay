import type { Metadata } from "next";

import { Notifications } from "./notifications";

export const metadata: Metadata = { title: "Мэдэгдэл" };

export default function NotificationsPage() {
  return <Notifications />;
}
