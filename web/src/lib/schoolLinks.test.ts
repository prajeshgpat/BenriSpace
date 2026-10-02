import { describe, expect, it } from "vitest";

import { GREATSCHOOLS_DISTRICTS_URL } from "./schoolLinks";

describe("schoolLinks", () => {
  it("points at the GreatSchools district map", () => {
    expect(GREATSCHOOLS_DISTRICTS_URL).toBe(
      "https://www.greatschools.org/school-district-boundaries-map/",
    );
  });
});
