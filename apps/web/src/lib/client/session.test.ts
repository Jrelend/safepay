import { describe, expect, it } from "vitest";

import { safeNext } from "./session";

describe("safeNext", () => {
  it("keeps same-site paths", () => {
    expect(safeNext("/deals/abc")).toBe("/deals/abc");
  });
  it("rejects open redirects", () => {
    for (const bad of ["https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", null, ""]) {
      expect(safeNext(bad)).toBe("/dashboard");
    }
  });
});
