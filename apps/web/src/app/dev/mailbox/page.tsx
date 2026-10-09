import type { Metadata } from "next";

import { Mailbox } from "./mailbox";

export const metadata: Metadata = { title: "Туршилтын шуудан" };

export default function MailboxPage() {
  return <Mailbox />;
}
