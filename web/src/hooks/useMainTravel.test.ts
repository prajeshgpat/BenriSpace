import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useMainTravel } from "./useMainTravel";

describe("useMainTravel", () => {
  it("starts dense places on a 20 min train", () => {
    const { result } = renderHook(() => useMainTravel("walk"));
    expect(result.current).toMatchObject({ mode: "transit", minutes: 20, chosen: false });
  });

  it("starts other places on a 15 min drive", () => {
    for (const m of ["drive", null, undefined] as const) {
      const { result } = renderHook(() => useMainTravel(m));
      expect(result.current).toMatchObject({ mode: "drive", minutes: 15, chosen: false });
    }
  });

  it("follows the place until something is picked", () => {
    const { result, rerender } = renderHook(({ m }) => useMainTravel(m), {
      initialProps: { m: "drive" as "walk" | "drive" | null },
    });
    rerender({ m: "walk" });
    expect(result.current).toMatchObject({ mode: "transit", minutes: 20 });
    // A place still loading (null) keeps what is shown.
    rerender({ m: null });
    expect(result.current).toMatchObject({ mode: "transit", minutes: 20 });
    act(() => result.current.set("walk", 10));
    expect(result.current).toMatchObject({ mode: "walk", minutes: 10, chosen: true });
    rerender({ m: "drive" });
    expect(result.current).toMatchObject({ mode: "walk", minutes: 10, chosen: true });
  });
});
