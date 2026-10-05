import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { ChatReply } from "@/lib/api/types";
import { stubClient } from "@/test/fixtures";

import {
  CHAT_INPUT_LIMIT,
  CHAT_STORAGE_KEY,
  ChatPanel,
  STARTER_QUESTIONS,
} from "./ChatPanel";

const REPLY: ChatReply = {
  reply: "Shippan Point looks best.",
  results: [
    { label: "Shippan Point, Stamford", latitude: 41.01, longitude: -73.52, score: 85, weeklyMinutes: 243, why: "Short trips to all three." },
    { label: "Darien, CT", latitude: 41.07, longitude: -73.47, score: 87, weeklyMinutes: 274, why: "Higher score." },
  ],
  sources: [],
  limited: false,
};

function setup(chat: ApiClient["chat"] = vi.fn(async () => REPLY), props = {}) {
  const client = stubClient({ chat });
  const handlers = { onShowOnMap: vi.fn(), onScoreArea: vi.fn(), onClose: vi.fn() };
  render(<ChatPanel client={client} {...handlers} {...props} />);
  return { chat: chat as ReturnType<typeof vi.fn>, ...handlers };
}

beforeEach(() => window.sessionStorage.clear());

describe("ChatPanel", () => {
  it("offers the three starter questions, which send immediately", async () => {
    const user = userEvent.setup();
    const { chat } = setup();
    const chips = within(screen.getByRole("list", { name: "Suggested questions" })).getAllByRole("button");
    expect(chips.map((c) => c.textContent)).toEqual([...STARTER_QUESTIONS]);

    await user.click(chips[0]);

    await screen.findByText("Shippan Point looks best.");
    expect(chat).toHaveBeenCalledWith(
      [{ role: "user", content: STARTER_QUESTIONS[0] }],
      undefined,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(screen.queryByRole("list", { name: "Suggested questions" })).not.toBeInTheDocument();
  });

  it("sends on Enter, keeps Shift+Enter for a newline, and sends the context", async () => {
    const user = userEvent.setup();
    const context = { address: "5 Main St", latitude: 40.7, longitude: -74, factors: ["grocery" as const] };
    const { chat } = setup(undefined, { context });
    const box = screen.getByRole("textbox", { name: "Your question" });

    await user.type(box, "line one{Shift>}{Enter}{/Shift}line two");
    expect(box).toHaveValue("line one\nline two");
    expect(chat).not.toHaveBeenCalled();

    await user.keyboard("{Enter}");
    await screen.findByText("Shippan Point looks best.");
    expect((chat.mock.calls as unknown[][])[0][0]).toEqual([{ role: "user", content: "line one\nline two" }]);
    expect(chat.mock.calls[0][1]).toEqual(context);
    expect(box).toHaveValue("");
  });

  it("limits the input to 500 characters and shows a counter near the limit", async () => {
    const user = userEvent.setup();
    setup();
    const box = screen.getByRole("textbox", { name: "Your question" });
    expect(box).toHaveAttribute("maxlength", String(CHAT_INPUT_LIMIT));
    await user.click(box);
    await user.paste("a".repeat(450));
    expect(screen.getByText("450/500")).toBeVisible();
  });

  it("shows a typing indicator while waiting, in a polite live log", async () => {
    const user = userEvent.setup();
    let resolve!: (r: ChatReply) => void;
    setup(vi.fn(() => new Promise<ChatReply>((r) => (resolve = r))));
    expect(screen.getByRole("log", { name: "Conversation" })).toHaveAttribute("aria-live", "polite");

    await user.type(screen.getByRole("textbox"), "hello{Enter}");
    expect(await screen.findByRole("status", { name: "BenriSpace is typing" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();

    resolve(REPLY);
    await screen.findByText("Shippan Point looks best.");
    expect(screen.queryByRole("status", { name: "BenriSpace is typing" })).not.toBeInTheDocument();
  });

  it("renders result cards whose buttons call the map and score handlers", async () => {
    const user = userEvent.setup();
    const { onShowOnMap, onScoreArea } = setup();
    await user.type(screen.getByRole("textbox"), "find{Enter}");

    const cards = await screen.findAllByRole("listitem", {}, { timeout: 2000 });
    const first = cards.find((c) => within(c).queryByText("Shippan Point, Stamford"))!;
    expect(within(first).getByText("Score 85 · 243 min a week")).toBeInTheDocument();

    await user.click(within(first).getByRole("button", { name: "Show Shippan Point, Stamford on map" }));
    expect(onShowOnMap).toHaveBeenCalledWith(REPLY.results[0]);
    await user.click(within(first).getByRole("button", { name: "Score Shippan Point, Stamford" }));
    expect(onScoreArea).toHaveBeenCalledWith(REPLY.results[0]);
  });

  it("keeps the conversation in sessionStorage and New chat clears it", async () => {
    const user = userEvent.setup();
    const { unmount } = render(
      <ChatPanel client={stubClient({ chat: vi.fn(async () => REPLY) })} onShowOnMap={vi.fn()} onScoreArea={vi.fn()} />,
    );
    await user.type(screen.getByRole("textbox"), "remember me{Enter}");
    await screen.findByText("Shippan Point looks best.");
    expect(JSON.parse(window.sessionStorage.getItem(CHAT_STORAGE_KEY)!)).toHaveLength(2);
    unmount();

    setup();
    expect(await screen.findByText("remember me")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "New chat" }));
    expect(screen.queryByText("remember me")).not.toBeInTheDocument();
    expect(window.sessionStorage.getItem(CHAT_STORAGE_KEY)).toBeNull();
    expect(screen.getByRole("list", { name: "Suggested questions" })).toBeInTheDocument();
  });

  it("only sends the stored history, never error text", async () => {
    const user = userEvent.setup();
    const chat = vi
      .fn<ApiClient["chat"]>()
      .mockRejectedValueOnce(new ApiError("network", "x"))
      .mockResolvedValueOnce(REPLY);
    setup(chat);
    await user.type(screen.getByRole("textbox"), "first{Enter}");
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByText("Shippan Point looks best.");
    expect(chat.mock.calls[1][0]).toEqual([{ role: "user", content: "first" }]);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    [new ApiError("rate-limited", "x", { status: 429 }), /15 chat questions/, false],
    [new ApiError("server", "x", { status: 503 }), /unavailable/, true],
    [new ApiError("network", "x"), /Couldn.t reach BenriSpace/, true],
    [new ApiError("timeout", "x"), /Couldn.t reach BenriSpace/, true],
  ])("shows a friendly error for %s", async (error, text, retryable) => {
    const user = userEvent.setup();
    setup(vi.fn(async () => { throw error; }));
    await user.type(screen.getByRole("textbox"), "q{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(screen.queryByRole("button", { name: "Try again" }) !== null).toBe(retryable);
  });

  it("Close chat calls onClose", async () => {
    const user = userEvent.setup();
    const { onClose } = setup();
    await user.click(screen.getByRole("button", { name: "Close chat" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("adds a client-side note when the place changes, and never sends it", async () => {
    const user = userEvent.setup();
    const chat = vi.fn(async () => REPLY);
    const client = stubClient({ chat });
    const handlers = { onShowOnMap: vi.fn(), onScoreArea: vi.fn() };
    const { rerender } = render(
      <ChatPanel client={client} {...handlers} place={{ key: "a", label: "Astoria" }} />,
    );
    expect(screen.queryByText(/Now looking at/)).not.toBeInTheDocument();
    rerender(
      <ChatPanel client={client} {...handlers} place={{ key: "b", label: "Park Slope, Brooklyn" }} />,
    );
    expect(await screen.findByText("Now looking at Park Slope, Brooklyn")).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Your question" }), "hi{Enter}");
    await screen.findByText("Shippan Point looks best.");
    expect((chat.mock.calls as unknown[][])[0][0]).toEqual([{ role: "user", content: "hi" }]);
    expect(window.sessionStorage.getItem(CHAT_STORAGE_KEY)).not.toContain("Now looking");
  });

  it("ignores a stale reply after New chat", async () => {
    const user = userEvent.setup();
    let resolve!: (r: ChatReply) => void;
    setup(vi.fn(() => new Promise<ChatReply>((r) => (resolve = r))));
    await user.type(screen.getByRole("textbox"), "slow{Enter}");
    await screen.findByRole("status", { name: "BenriSpace is typing" });
    await user.click(screen.getByRole("button", { name: "New chat" }));
    resolve(REPLY);
    await waitFor(() => expect(screen.queryByText("Shippan Point looks best.")).not.toBeInTheDocument());
  });
});
