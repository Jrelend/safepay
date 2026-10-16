import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { PUBLIC_ACTIONS } from "./deal-actions";
import {
  FLOW_STEPS,
  ISSUE_ACTIONS,
  MONEY_LOCATION,
  PRIMARY_ACTIONS,
  dealProgress,
  isTerminal,
  nextStep,
  splitActions,
  summaryNeedsMe,
} from "./deal-flow";
import { DEAL_STATUSES, type DealStatus } from "./deal-status";
import type { DealAction, Role } from "./types";

const STATES = fileURLToPath(new URL("../../../api/app/domain/deal_states.py", import.meta.url));
const src = readFileSync(STATES, "utf8");

function backendSet(name: string): string[] {
  const block = src.match(new RegExp(`${name}[^=]*=\\s*frozenset\\(\\s*\\{([^}]*)\\}`));
  if (!block) throw new Error(`${name} not found in backend source`);
  return [...block[1].matchAll(/_DS\.([A-Z_]+)/g)].map((m) => m[1]).sort();
}

/** (source, action) → actors, parsed from the backend TRANSITIONS table. */
function backendTransitions(): { source: string; action: string; actors: string[] }[] {
  return [...src.matchAll(/_t\(_DS\.([A-Z_]+), _DA\.([A-Z_]+), _DS\.[A-Z_]+((?:, _[A-Z]+)*)/g)].map((m) => ({
    source: m[1],
    action: m[2],
    actors: [...m[3].matchAll(/_(B|S|SYS|ADM)\b/g)].map((a) => a[1]),
  }));
}

describe("deal flow", () => {
  it("shows money as held exactly in the backend's escrow-held states", () => {
    const held = DEAL_STATUSES.filter((s) => ["HELD", "LOCKED"].includes(MONEY_LOCATION[s])).sort();
    expect(held).toEqual(backendSet("ESCROW_HELD_STATES"));
  });

  it("treats exactly the backend's terminal states as closed", () => {
    expect(DEAL_STATUSES.filter(isTerminal).sort()).toEqual(backendSet("TERMINAL_STATES"));
  });

  it("splits every participant action into primary or issue, never both", () => {
    const all = [...PRIMARY_ACTIONS, ...ISSUE_ACTIONS].sort();
    expect(all).toEqual([...PUBLIC_ACTIONS].sort());
    const { primary, issue } = splitActions([...PUBLIC_ACTIONS]);
    expect(primary).toHaveLength(PRIMARY_ACTIONS.length);
    expect(issue).toEqual([...ISSUE_ACTIONS]);
  });

  it("names the role the backend allows to move each funded state forward", () => {
    const actorFor = (status: string, action: string) =>
      backendTransitions().find((t) => t.source === status && t.action === action)?.actors;
    expect(actorFor("AWAITING_PAYMENT", "FUND")).toEqual(["B"]);
    expect(actorFor("FUNDED", "MARK_DELIVERED")).toEqual(["S"]);
    expect(actorFor("DELIVERED", "CONFIRM_RECEIPT")).toEqual(["B"]);

    const deal = (status: DealStatus, my_role: Role, actions: DealAction[] = []) => ({
      status,
      my_role,
      actions,
      counterparty_name: "Нөгөө",
      created_by_me: true,
    });
    expect(nextStep(deal("AWAITING_PAYMENT", "BUYER", ["FUND"])).turn).toBe("me");
    expect(nextStep(deal("AWAITING_PAYMENT", "SELLER")).turn).toBe("counterparty");
    expect(nextStep(deal("FUNDED", "SELLER", ["MARK_DELIVERED"])).turn).toBe("me");
    expect(nextStep(deal("FUNDED", "BUYER", ["OPEN_DISPUTE"])).turn).toBe("counterparty");
    expect(nextStep(deal("DELIVERED", "BUYER", ["CONFIRM_RECEIPT"])).turn).toBe("me");
    expect(nextStep(deal("DELIVERED", "SELLER")).turn).toBe("counterparty");
    expect(nextStep(deal("DISPUTED", "BUYER")).turn).toBe("safepay");
  });

  it("agrees with the list view's 'needs me' rule", () => {
    for (const status of ["AWAITING_PAYMENT", "FUNDED", "DELIVERED"] as const) {
      for (const my_role of ["BUYER", "SELLER"] as const) {
        const step = nextStep({ status, my_role, actions: [], counterparty_name: "Нөгөө", created_by_me: true });
        expect(summaryNeedsMe({ status, my_role })).toBe(step.turn === "me");
      }
    }
  });

  it("uses the allowed actions for agreement steps", () => {
    const base = { my_role: "SELLER" as const, counterparty_name: null, created_by_me: true };
    expect(nextStep({ ...base, status: "DRAFT", actions: ["SUBMIT", "CANCEL"] }).turn).toBe("me");
    expect(nextStep({ ...base, status: "DRAFT", actions: [] }).title).toContain("нэгдэх");
    expect(nextStep({ ...base, status: "PENDING_ACCEPTANCE", actions: ["ACCEPT"] }).turn).toBe("me");
    expect(nextStep({ ...base, status: "PENDING_ACCEPTANCE", actions: ["CANCEL"] }).turn).toBe("counterparty");
  });

  it("has Mongolian copy and a progress position for every state and role", () => {
    for (const status of DEAL_STATUSES) {
      for (const my_role of ["BUYER", "SELLER"] as const) {
        const step = nextStep({ status, my_role, actions: [], counterparty_name: "Нөгөө", created_by_me: false });
        expect(step.title).toMatch(/[А-ЯЁӨҮа-яёөү]/);
        expect(step.body.length).toBeGreaterThan(5);
        expect(isTerminal(status)).toBe(step.turn === "nobody");
      }
      const p = dealProgress(status);
      expect(p.current).toBeGreaterThanOrEqual(0);
      expect(p.current).toBeLessThanOrEqual(FLOW_STEPS.length);
    }
    expect(dealProgress("COMPLETED")).toEqual({ current: FLOW_STEPS.length, halted: null });
  });
});
