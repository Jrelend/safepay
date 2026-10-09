import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { errorMessage } from "./errors";

const API_DIR = fileURLToPath(new URL("../../../api/app/", import.meta.url));

function backendErrorCodes(): Set<string> {
  const codes = new Set<string>();
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, entry.name);
      if (entry.isDirectory()) walk(p);
      else if (p.endsWith(".py")) {
        const src = readFileSync(p, "utf8");
        for (const m of src.matchAll(/ApiError\(\s*[\w.]+,\s*"([a-z_]+)"/g)) codes.add(m[1]);
        for (const m of src.matchAll(/\(\d{3}, "([a-z_]+)"\)/g)) codes.add(m[1]);
        for (const m of src.matchAll(/(?:Error|DraftError|InviteError)\("([a-z_]+)"\)/g)) codes.add(m[1]);
      }
    }
  };
  walk(API_DIR);
  return codes;
}

describe("error messages", () => {
  it("cover every error code the API can return", () => {
    const generic = errorMessage("definitely_unknown_code");
    const codes = backendErrorCodes();
    expect(codes.size).toBeGreaterThan(20);
    const missing = [...codes].filter((c) => errorMessage(c) === generic);
    expect(missing).toEqual([]);
  });
});
