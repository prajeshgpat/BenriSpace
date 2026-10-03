import { createEvent, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { SheetSnap } from "@/lib/sheetSnap";

import { BottomSheet } from "./BottomSheet";

function Harness({
  initial = "peek",
  onChange,
}: {
  initial?: SheetSnap;
  onChange?: (snap: SheetSnap) => void;
}) {
  const [snap, setSnap] = useState<SheetSnap>(initial);
  return (
    <BottomSheet
      snap={snap}
      label="Search and map controls"
      onSnapChange={(next) => {
        onChange?.(next);
        setSnap(next);
      }}
    >
      <input aria-label="Search" />
    </BottomSheet>
  );
}

const handle = () => screen.getByRole("button", { name: "Resize results panel" });
const sheet = () => screen.getByRole("complementary");

describe("BottomSheet", () => {
  it("renders a labelled region with a handle button that reports expansion", () => {
    render(<Harness />);
    expect(
      screen.getByRole("complementary", { name: "Search and map controls" }),
    ).toHaveAttribute("data-snap", "peek");
    expect(handle()).toHaveAttribute("aria-expanded", "false");
  });

  it("cycles peek, half, full, peek with Enter and Space", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    handle().focus();

    await user.keyboard("{Enter}");
    expect(sheet()).toHaveAttribute("data-snap", "half");
    expect(handle()).toHaveAttribute("aria-expanded", "true");
    await user.keyboard(" ");
    expect(sheet()).toHaveAttribute("data-snap", "full");
    await user.keyboard("{Enter}");
    expect(sheet()).toHaveAttribute("data-snap", "peek");
  });

  it("moves one snap with the arrow keys and stops at the ends", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    handle().focus();

    await user.keyboard("{ArrowDown}");
    expect(sheet()).toHaveAttribute("data-snap", "peek");
    await user.keyboard("{ArrowUp}");
    expect(sheet()).toHaveAttribute("data-snap", "half");
    await user.keyboard("{ArrowUp}{ArrowUp}");
    expect(sheet()).toHaveAttribute("data-snap", "full");
    await user.keyboard("{ArrowDown}");
    expect(sheet()).toHaveAttribute("data-snap", "half");
  });

  it("opens to half when focus lands in the collapsed body", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByLabelText("Search"));
    expect(sheet()).toHaveAttribute("data-snap", "half");
  });

  it("follows a drag and settles on the snap it is released nearest to", () => {
    const onChange = vi.fn();
    render(<Harness initial="half" onChange={onChange} />);
    // jsdom has no layout: give the sheet and the peek probe a size.
    Object.defineProperty(sheet(), "offsetHeight", { value: 800 });
    Object.defineProperty(sheet().firstElementChild!, "offsetHeight", {
      value: 100,
    });

    fireEvent.pointerDown(handle(), { pointerId: 1, clientY: 400, timeStamp: 0 });
    fireEvent.pointerMove(handle(), { pointerId: 1, clientY: 250, timeStamp: 500 });
    expect(sheet().style.transform).toBe("translateY(250px)");
    expect(sheet().className).toContain("dragging");

    fireEvent.pointerMove(handle(), { pointerId: 1, clientY: 60, timeStamp: 1000 });
    fireEvent.pointerUp(handle(), { pointerId: 1, clientY: 60, timeStamp: 1000 });
    expect(onChange).toHaveBeenCalledWith("full");
    expect(sheet().style.transform).toBe("");
    expect(sheet().className).not.toContain("dragging");

    // The click that follows a drag must not also cycle the snap.
    fireEvent.click(handle());
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(sheet()).toHaveAttribute("data-snap", "full");
  });

  it("treats a tap as a click, not a drag", () => {
    render(<Harness />);
    fireEvent.pointerDown(handle(), { pointerId: 1, clientY: 400 });
    fireEvent.pointerUp(handle(), { pointerId: 1, clientY: 402 });
    fireEvent.click(handle());
    expect(sheet()).toHaveAttribute("data-snap", "half");
  });

  it("does not change snap when a drag is cancelled", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    Object.defineProperty(sheet(), "offsetHeight", { value: 800 });
    fireEvent.pointerDown(handle(), { pointerId: 1, clientY: 700 });
    fireEvent.pointerMove(handle(), { pointerId: 1, clientY: 300 });
    fireEvent.pointerCancel(handle(), { pointerId: 1 });
    expect(onChange).not.toHaveBeenCalled();
    expect(sheet().style.transform).toBe("");
  });

  describe("swiping down from the body of the full sheet", () => {
    const body = () => screen.getByLabelText("Search").parentElement!;

    function swipe(startY: number, endY: number, scrollTop = 0) {
      Object.defineProperty(sheet(), "offsetHeight", { value: 800 });
      Object.defineProperty(sheet().firstElementChild!, "offsetHeight", {
        value: 100,
      });
      Object.defineProperty(body(), "scrollTop", {
        value: scrollTop,
        configurable: true,
      });
      // Explicit timestamps: a slow, deliberate swipe (about 0.2 px per ms, no flick): the release velocity must not depend on how fast
      // the test machine happens to dispatch three events.
      const dispatch = (
        make: typeof createEvent.touchStart,
        init: object,
        timeStamp: number,
      ) => {
        const event = make(body(), init);
        Object.defineProperty(event, "timeStamp", { value: timeStamp });
        fireEvent(body(), event);
      };
      dispatch(createEvent.touchStart, { touches: [{ clientY: startY }] }, 0);
      dispatch(createEvent.touchMove, { touches: [{ clientY: endY }] }, 2000);
      dispatch(createEvent.touchEnd, { changedTouches: [{ clientY: endY }] }, 2020);
    }

    it("shrinks the sheet when the body is scrolled to the top", () => {
      const onChange = vi.fn();
      render(<Harness initial="full" onChange={onChange} />);
      swipe(100, 520);
      expect(onChange).toHaveBeenCalledWith("half");
    });

    it("leaves a scrolled body, an upward swipe and other snaps alone", () => {
      const onChange = vi.fn();
      const { unmount } = render(<Harness initial="full" onChange={onChange} />);
      swipe(100, 520, 30);
      swipe(520, 100);
      expect(onChange).not.toHaveBeenCalled();
      unmount();
      render(<Harness initial="half" onChange={onChange} />);
      swipe(100, 520);
      expect(onChange).not.toHaveBeenCalled();
    });
  });
});
