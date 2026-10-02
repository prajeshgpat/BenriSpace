import { describe, expect, it } from "vitest";

import nextConfig, { LEGACY_APP_QUERY_KEYS, legacyAppRedirects } from "../next.config";

describe("legacy app redirects", () => {
  it("has one temporary rule per query key, from / to /app", async () => {
    const rules = await nextConfig.redirects!();
    expect(rules).toEqual(legacyAppRedirects());
    expect(rules.map((rule) => rule.has?.[0])).toEqual(
      LEGACY_APP_QUERY_KEYS.map((key) => ({ type: "query", key })),
    );
    for (const rule of rules) {
      expect(rule.source).toBe("/");
      expect(rule.destination).toBe("/app");
      expect(rule.permanent).toBe(false);
    }
  });

  it("covers every parameter the app writes", () => {
    expect([...LEGACY_APP_QUERY_KEYS]).toEqual(
      expect.arrayContaining(["address", "lat", "lon", "center", "z", "factors", "importance"]),
    );
  });

  it("keeps the security headers on every path", async () => {
    const [entry] = await nextConfig.headers!();
    expect(entry.source).toBe("/:path*");
    expect(entry.headers.map((h) => h.key)).toContain("X-Frame-Options");
  });
});
