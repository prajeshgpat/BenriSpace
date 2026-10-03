import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ALL_FACTOR_KEYS } from "@/lib/score/factors";

import { FACTOR_ICONS, FactorIcon } from "./factorIcons";

describe("factor icons", () => {
  it("has a decorative 24x24 stroke icon for every factor", () => {
    for (const key of ALL_FACTOR_KEYS) {
      const { container } = render(<FactorIcon factor={key} />);
      const svg = container.querySelector("svg");
      expect(svg, key).not.toBeNull();
      expect(svg).toHaveAttribute("viewBox", "0 0 24 24");
      expect(svg).toHaveAttribute("aria-hidden", "true");
      expect(svg).toHaveAttribute("stroke", "currentColor");
      expect(svg).toHaveAttribute("stroke-width", "2");
      expect(svg).toHaveAttribute("stroke-linecap", "round");
      expect(svg).toHaveAttribute("data-icon", key);
    }
  });

  it("covers every key of the registry", () => {
    expect(Object.keys(FACTOR_ICONS).sort()).toEqual([...ALL_FACTOR_KEYS].sort());
  });
});
