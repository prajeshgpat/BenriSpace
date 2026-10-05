import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatReply } from "@/lib/api/types";
import { stubClient } from "@/test/fixtures";

import { ChatDock, DOCK_MIN, DOCK_STORAGE_KEY } from "./ChatDock";

const REPLY: ChatReply = { reply: "Try Astoria.", results: [], sources: [], limited: false };

function setup(chat = vi.fn(async () => REPLY)) {
  const onClose = vi.fn();
  render(
    <div style={{ height: 800 }}>
      <ChatDock
        client={stubClient({ chat })}
        onShowOnMap={vi.fn()}
        onScoreArea={vi.fn()}
        onClose={onClose}
      />
    </div>,
  );
  return { chat, onClose };
}

const handle = () => screen.getByRole("separator", { name: "Resize chat" });

beforeEach(() => window.sessionStorage.clear());

describe("ChatDock", () => {
  it("is a labelled region with focus in the input and a horizontal separator", () => {
    setup();
    expect(screen.getByRole("region", { name: "Ask BenriSpace" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Your question" })).toHaveFocus();
    expect(handle()).toHaveAttribute("aria-orientation", "horizontal");
    expect(handle()).toHaveAttribute("aria-valuemin", String(DOCK_MIN));
    expect(Number(handle().getAttribute("aria-valuemax"))).toBeGreaterThan(DOCK_MIN);
    expect(Number(handle().getAttribute("aria-valuenow"))).toBeGreaterThanOrEqual(DOCK_MIN);
  });

  it("resizes with the arrow keys within limits and remembers the size", () => {
    setup();
    const start = Number(handle().getAttribute("aria-valuenow"));
    fireEvent.keyDown(handle(), { key: "ArrowUp" });
    expect(Number(handle().getAttribute("aria-valuenow"))).toBe(start + 24);
    expect(window.sessionStorage.getItem(DOCK_STORAGE_KEY)).toBe(String(start + 24));
    fireEvent.keyDown(handle(), { key: "Home" });
    expect(handle()).toHaveAttribute("aria-valuenow", String(DOCK_MIN));
    fireEvent.keyDown(handle(), { key: "ArrowDown" });
    expect(handle()).toHaveAttribute("aria-valuenow", String(DOCK_MIN));
    fireEvent.keyDown(handle(), { key: "End" });
    expect(handle().getAttribute("aria-valuenow")).toBe(handle().getAttribute("aria-valuemax"));
  });

  it("restores the remembered size", () => {
    window.sessionStorage.setItem(DOCK_STORAGE_KEY, "300");
    setup();
    expect(handle()).toHaveAttribute("aria-valuenow", "300");
  });

  it("collapses with Escape and the button, keeping only the bar", async () => {
    const user = userEvent.setup();
    setup();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Expand" })).toHaveFocus();
    expect(screen.queryByRole("textbox", { name: "Your question" })).not.toBeInTheDocument();
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Expand" }));
    expect(await screen.findByRole("textbox", { name: "Your question" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Collapse" }));
    expect(screen.getByRole("button", { name: "Expand" })).toHaveAttribute("aria-expanded", "false");
  });

  it("shows an unread dot for a reply that lands while collapsed", async () => {
    const user = userEvent.setup();
    let resolve: (r: ChatReply) => void = () => {};
    setup(vi.fn(() => new Promise<ChatReply>((r) => (resolve = r))));
    await user.type(screen.getByRole("textbox", { name: "Your question" }), "hi{Enter}");
    await user.click(screen.getByRole("button", { name: "Collapse" }));
    expect(screen.queryByText("New reply")).not.toBeInTheDocument();
    await act(async () => resolve(REPLY));
    expect(screen.getByText("New reply")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Expand" }));
    expect(screen.queryByText("New reply")).not.toBeInTheDocument();
    expect(screen.getByText("Try Astoria.")).toBeInTheDocument();
  });

  it("Close calls onClose", async () => {
    const user = userEvent.setup();
    const { onClose } = setup();
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalled();
  });
});
