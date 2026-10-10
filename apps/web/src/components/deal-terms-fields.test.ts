import { describe, expect, it } from "vitest";

import { parseAmountInput } from "./deal-terms-fields";

describe("parseAmountInput", () => {
  it("accepts grouped integers", () => {
    expect(parseAmountInput("1,250,000")).toBe(1_250_000);
    expect(parseAmountInput("1 250 000 ₮")).toBe(1_250_000);
    expect(parseAmountInput("100")).toBe(100);
    expect(parseAmountInput("100000000000")).toBe(100_000_000_000);
  });
  it("rejects fractions, negatives, out-of-range and junk", () => {
    for (const bad of ["99", "-500", "1e6", "12.5abc", "", "abc", "100000000001", "0x10"]) {
      expect(parseAmountInput(bad)).toBeNull();
    }
  });
});
