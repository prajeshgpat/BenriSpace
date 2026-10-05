import { expect, it } from "vitest";

import { daysAgo } from "./timeAgo";

it("describes age in days", () => {
  const now = new Date("2026-10-04T12:00:00Z");
  expect(daysAgo("2026-10-04T01:00:00Z", now)).toBe("today");
  expect(daysAgo("2026-10-03T00:00:00Z", now)).toBe("1 day ago");
  expect(daysAgo("2026-09-24T12:00:00Z", now)).toBe("10 days ago");
  expect(daysAgo(null, now)).toBe("unknown");
  expect(daysAgo("junk", now)).toBe("unknown");
});
