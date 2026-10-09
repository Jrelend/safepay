import { describe, expect, it } from "vitest";

import {
  clientAddress,
  downstreamResponseHeaders,
  resolveUpstream,
  upstreamRequestHeaders,
} from "./proxy";

const env = { publicUrl: "http://api:8000", adminUrl: "http://admin-api:8000" };

describe("resolveUpstream", () => {
  it("routes admin paths to the admin service only", () => {
    expect(resolveUpstream(["admin", "overview"], env)).toEqual({
      base: "http://admin-api:8000",
      path: "/admin/overview",
    });
    expect(resolveUpstream(["deals", "abc"], env)?.base).toBe("http://api:8000");
    expect(resolveUpstream(["admin", "x"], { ...env, adminUrl: undefined })).toBeNull();
  });

  it("rejects traversal, encoded separators and operational endpoints", () => {
    for (const bad of [[".."], ["deals", ".."], ["a%2Fb"], ["a/b"], ["health"], ["docs"], []]) {
      expect(resolveUpstream(bad, env)).toBeNull();
    }
  });
});

describe("headers", () => {
  it("forwards only allow-listed request headers and one client address", () => {
    const h = upstreamRequestHeaders(
      new Headers({
        cookie: "safepay_session=abc",
        "x-csrf-token": "t",
        authorization: "Bearer stolen",
        host: "evil",
        "x-forwarded-for": "6.6.6.6, 10.0.0.7",
        "x-admin": "1",
      }),
    );
    expect(h.get("cookie")).toBe("safepay_session=abc");
    expect(h.get("x-csrf-token")).toBe("t");
    expect(h.get("authorization")).toBeNull();
    expect(h.get("host")).toBeNull();
    expect(h.get("x-admin")).toBeNull();
    expect(h.get("x-forwarded-for")).toBe("10.0.0.7");
  });

  it("uses the right-most hop", () => {
    expect(clientAddress("1.1.1.1")).toBe("1.1.1.1");
    expect(clientAddress("spoofed, 2.2.2.2")).toBe("2.2.2.2");
    expect(clientAddress(null)).toBeNull();
  });

  it("passes cookies back and defaults to no-store", () => {
    const up = new Headers({ "content-type": "application/json", server: "uvicorn" });
    up.append("set-cookie", "a=1; HttpOnly");
    up.append("set-cookie", "b=2");
    const out = downstreamResponseHeaders(up);
    expect(out.getSetCookie()).toEqual(["a=1; HttpOnly", "b=2"]);
    expect(out.get("server")).toBeNull();
    expect(out.get("cache-control")).toBe("no-store");
  });
});
