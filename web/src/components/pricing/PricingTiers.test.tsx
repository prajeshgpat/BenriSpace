import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { PricingFaq } from "./PricingFaq";
import { PricingTiers } from "./PricingTiers";

describe("PricingTiers", () => {
  it("shows three tiers with Pro recommended and placeholder pricing", () => {
    render(<PricingTiers />);
    for (const name of ["Free", "Pro", "Business"]) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
    const pro = screen.getByRole("region", { name: "Pro" });
    expect(within(pro).getByText("Recommended")).toBeInTheDocument();
    expect(within(pro).getByText("Placeholder price")).toBeInTheDocument();
    expect(
      screen.getByText("Ask Benri chat, 15 messages a day"),
    ).toBeInTheDocument();
  });

  it("switches Pro between monthly and yearly prices", async () => {
    const user = userEvent.setup();
    render(<PricingTiers />);
    const pro = screen.getByRole("region", { name: "Pro" });
    expect(pro).toHaveTextContent("$9 / month");
    await user.click(screen.getByRole("button", { name: "Yearly" }));
    expect(pro).toHaveTextContent("$90 / year");
  });

  it("sends Free to the app and the paid tiers to login", () => {
    render(<PricingTiers />);
    expect(
      screen.getByRole("link", { name: "Start for free" }),
    ).toHaveAttribute("href", "/app");
    expect(screen.getByRole("link", { name: "Choose Pro" })).toHaveAttribute(
      "href",
      "/login",
    );
    expect(screen.getByRole("link", { name: "Contact us" })).toHaveAttribute(
      "href",
      "/login",
    );
  });
});

describe("PricingFaq", () => {
  it("lists the questions, including the beta note", () => {
    render(<PricingFaq />);
    expect(
      screen.getByText("Is BenriSpace free right now?"),
    ).toBeInTheDocument();
    expect(screen.getByText(/free while it is in beta/)).toBeInTheDocument();
  });
});
