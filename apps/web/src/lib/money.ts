/**
 * MNT (Mongolian tögrög) formatting.
 *
 * SafePay amounts are always whole tögrög (integers). The backend stores them
 * as BIGINT, which can exceed Number.MAX_SAFE_INTEGER, so `bigint` and
 * integer strings are accepted as well as safe-integer numbers.
 */

export const MNT_SYMBOL = "₮";

export function parseMnt(value: number | bigint | string): bigint {
  if (typeof value === "bigint") return value;
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) {
      throw new RangeError(`MNT amount must be a safe integer, got ${value}`);
    }
    return BigInt(value);
  }
  if (!/^-?\d+$/.test(value)) {
    throw new RangeError(`MNT amount must be an integer string, got "${value}"`);
  }
  return BigInt(value);
}

/** Format as e.g. "1,250,000 ₮". */
export function formatMnt(value: number | bigint | string): string {
  const amount = parseMnt(value);
  const negative = amount < BigInt(0);
  const digits = (negative ? -amount : amount).toString();
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative ? "-" : ""}${grouped} ${MNT_SYMBOL}`;
}
