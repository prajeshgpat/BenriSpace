import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FeedbackThumbs, ReportProblem } from "./Feedback";

describe("FeedbackThumbs", () => {
  it("sends a rating and thanks the user", async () => {
    const sendFeedback = vi.fn(async () => {});
    render(<FeedbackThumbs client={{ sendFeedback }} kind="summary" target="Park Slope" />);
    await userEvent.click(screen.getByRole("button", { name: /^No/ }));
    expect(sendFeedback).toHaveBeenCalledWith({ kind: "summary", rating: -1, target: "Park Slope" });
    expect(screen.getByRole("status")).toHaveTextContent("Thanks");
  });

  it("stays friendly and silent when sending fails", async () => {
    const sendFeedback = vi.fn(async () => {
      throw new Error("offline");
    });
    render(<FeedbackThumbs client={{ sendFeedback }} kind="chat" target="Answer" />);
    await userEvent.click(screen.getByRole("button", { name: /^Yes/ }));
    expect(screen.getByRole("status")).toHaveTextContent("Thanks");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("renders nothing without a client", () => {
    const { container } = render(<FeedbackThumbs kind="chat" target="x" />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ReportProblem", () => {
  it("opens a form and posts a place report", async () => {
    const sendFeedback = vi.fn(async () => {});
    render(<ReportProblem client={{ sendFeedback }} list="Best areas" />);
    await userEvent.click(screen.getByRole("button", { name: "Report a problem" }));
    await userEvent.click(screen.getByLabelText(/has closed/));
    await userEvent.type(screen.getByLabelText(/Which place/), "Joe's Cafe");
    await userEvent.click(screen.getByRole("button", { name: "Send report" }));
    expect(sendFeedback).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "place", message: expect.stringContaining("Joe's Cafe") }),
    );
    expect(screen.getByRole("status")).toHaveTextContent("Thanks");
  });
});
