import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { DEAL_STATUSES, DEAL_STATUS_META } from "./deal-status";

const BACKEND_STATES = fileURLToPath(
  new URL("../../../api/app/domain/deal_states.py", import.meta.url),
);

function backendStatuses(): string[] {
  const source = readFileSync(BACKEND_STATES, "utf8");
  const block = source.match(/class DealStatus\(StrEnum\):\n((?:    .*\n)+)/);
  if (!block) throw new Error("DealStatus enum not found in backend source");
  return [...block[1].matchAll(/^ {4}([A-Z_]+) = "([A-Z_]+)"$/gm)].map((m) => m[2]);
}

describe("deal statuses", () => {
  it("mirror the backend state machine exactly", () => {
    expect([...DEAL_STATUSES]).toEqual(backendStatuses());
  });

  it("have Mongolian labels and descriptions for every state", () => {
    for (const status of DEAL_STATUSES) {
      const meta = DEAL_STATUS_META[status];
      expect(meta.label).toMatch(/[А-ЯЁӨҮа-яёөү]/);
      expect(meta.description.length).toBeGreaterThan(5);
    }
  });
});
