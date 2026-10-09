import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { ACTION_META, PUBLIC_ACTIONS } from "./deal-actions";

const TRANSITIONS = fileURLToPath(new URL("../../../api/app/services/deal_transitions.py", import.meta.url));

describe("deal actions", () => {
  it("match the backend's participant actions", () => {
    const src = readFileSync(TRANSITIONS, "utf8");
    const block = src.match(/PUBLIC_ACTIONS[^=]*=\s*frozenset\(\s*\{([^}]*)\}/);
    expect(block).not.toBeNull();
    const backend = [...block![1].matchAll(/DealAction\.([A-Z_]+)/g)].map((m) => m[1]).sort();
    expect([...PUBLIC_ACTIONS].sort()).toEqual(backend);
  });

  it("flag the money-moving actions", () => {
    const money = Object.entries(ACTION_META)
      .filter(([, m]) => m.money)
      .map(([a]) => a)
      .sort();
    expect(money).toEqual(["CONFIRM_RECEIPT", "FUND", "REFUND"]);
    expect(ACTION_META.OPEN_DISPUTE.needsNote).toBe(true);
  });
});
