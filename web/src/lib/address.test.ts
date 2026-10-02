import { describe, expect, it } from "vitest";

import { ADDRESS_MAX_LENGTH, resultHref, validateAddress } from "./address";

describe("validateAddress", () => {
  it("trims and collapses whitespace", () => {
    expect(validateAddress("  350   5th Ave,\tNew York  ")).toEqual({
      ok: true,
      value: "350 5th Ave, New York",
    });
  });

  it.each(["", "   ", "\n\t"])("rejects blank input %j", (input) => {
    expect(validateAddress(input)).toEqual({
      ok: false,
      message: "Enter an address to score.",
    });
  });

  it("rejects input too short to be an address", () => {
    const result = validateAddress("ab");

    expect(result.ok).toBe(false);
  });

  it("accepts an address at the length limit and rejects one past it", () => {
    expect(validateAddress("a".repeat(ADDRESS_MAX_LENGTH)).ok).toBe(true);
    expect(validateAddress("a".repeat(ADDRESS_MAX_LENGTH + 1)).ok).toBe(false);
  });
});

describe("resultHref", () => {
  it("builds a shareable URL that round-trips the address", () => {
    const address = "350 5th Ave, New York, NY #2 & more";
    const href = resultHref(address);

    expect(href.startsWith("/app?address=")).toBe(true);
    expect(new URL(href, "https://benrispace.com").searchParams.get("address")).toBe(
      address,
    );
  });
});
