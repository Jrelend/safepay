import { describe, expect, it } from "vitest";

import { readCsrfToken } from "./api";

describe("readCsrfToken", () => {
  it("reads either cookie name", () => {
    expect(readCsrfToken("a=1; safepay_csrf=tok%3D; b=2")).toBe("tok=");
    expect(readCsrfToken("__Host-safepay_csrf=x")).toBe("x");
  });
  it("does not confuse similarly named cookies", () => {
    expect(readCsrfToken("evil_safepay_csrf=x; safepay_csrf2=y")).toBeNull();
  });
});
