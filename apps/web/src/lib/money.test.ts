import { describe, expect, it } from "vitest";

import { formatMnt, parseMnt } from "./money";

describe("formatMnt", () => {
  it.each([
    [0, "0 ₮"],
    [500, "500 ₮"],
    [1_000, "1,000 ₮"],
    [1_250_000, "1,250,000 ₮"],
    [-45_000, "-45,000 ₮"],
  ])("formats %s as %s", (input, expected) => {
    expect(formatMnt(input)).toBe(expected);
  });

  it("formats BIGINT-sized amounts without precision loss", () => {
    expect(formatMnt("9223372036854775807")).toBe("9,223,372,036,854,775,807 ₮");
    expect(formatMnt(BigInt("9007199254740993"))).toBe("9,007,199,254,740,993 ₮");
  });

  it.each([1.5, Number.NaN, Number.POSITIVE_INFINITY, 2 ** 60])("rejects %s", (bad) => {
    expect(() => formatMnt(bad)).toThrow(RangeError);
  });

  it.each(["1.5", "", "1e6", "١٢٣", " 10"])("rejects string %j", (bad) => {
    expect(() => parseMnt(bad)).toThrow(RangeError);
  });
});
