import { createEvent, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { SheetSnap } from "@/lib/sheetSnap";

import { BottomSheet } from "./BottomSheet";

function Harness({
  initial = "peek",
  onChange,
  onPress,
}: {
  initial?: SheetSnap;
  onChange?: (snap: SheetSnap) => void;
  onPress?: () => void;
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
      <button type="button" onClick={onPress}>
        Press me
      </button>
      <ul role="listbox" aria-label="Suggestions">
        <li role="option" aria-selected="false">
          One
        </li>
      </ul>
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

  describe("dragging from the body", () => {
    const body = () => screen.getByLabelText("Search").parentElement!;

    function swipe(
      startY: number,
      endY: number,
      { scrollTop = 0, target = body(), dx = 0 }: { scrollTop?: number; target?: Element; dx?: number } = {},
    ) {
      Object.defineProperty(sheet(), "offsetHeight", { value: 800, configurable: true });
      Object.defineProperty(sheet().firstElementChild!, "offsetHeight", {
        value: 100,
        configurable: true,
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
        const event = make(target, init);
        Object.defineProperty(event, "timeStamp", { value: timeStamp });
        fireEvent(target, event);
        return event;
      };
      dispatch(createEvent.touchStart, { touches: [{ clientX: 50, clientY: startY }] }, 0);
      const move = dispatch(
        createEvent.touchMove,
        { cancelable: true, touches: [{ clientX: 50 + dx, clientY: endY }] },
        2000,
      );
      dispatch(createEvent.touchEnd, { changedTouches: [{ clientY: endY }] }, 2020);
      return move;
    }

    it("shrinks the full sheet when the body is scrolled to the top", () => {
      const onChange = vi.fn();
      render(<Harness initial="full" onChange={onChange} />);
      swipe(100, 520);
      expect(onChange).toHaveBeenCalledWith("half");
    });

    it("leaves a scrolled full sheet and an upward swipe on it to scroll", () => {
      const onChange = vi.fn();
      render(<Harness initial="full" onChange={onChange} />);
      swipe(100, 520, { scrollTop: 30 });
      const up = swipe(520, 100);
      expect(onChange).not.toHaveBeenCalled();
      expect(up.defaultPrevented).toBe(false);
    });

    it("opens the half sheet to full when dragged up from anywhere in the body", () => {
      const onChange = vi.fn();
      render(<Harness initial="half" onChange={onChange} />);
      const move = swipe(520, 100);
      expect(move.defaultPrevented).toBe(true);
      expect(onChange).toHaveBeenCalledWith("full");
    });

    it("closes the half sheet to peek when dragged down", () => {
      const onChange = vi.fn();
      render(<Harness initial="half" onChange={onChange} />);
      swipe(100, 520);
      expect(onChange).toHaveBeenCalledWith("peek");
    });

    it("moves the collapsed sheet up too", () => {
      const onChange = vi.fn();
      render(<Harness initial="peek" onChange={onChange} />);
      swipe(700, 100);
      expect(onChange).toHaveBeenCalledWith("full");
    });

    it("follows the finger while dragging", () => {
      render(<Harness initial="half" />);
      Object.defineProperty(sheet(), "offsetHeight", { value: 800, configurable: true });
      Object.defineProperty(sheet().firstElementChild!, "offsetHeight", { value: 100, configurable: true });
      fireEvent(body(), createEvent.touchStart(body(), { touches: [{ clientX: 0, clientY: 500 }] }));
      fireEvent(body(), createEvent.touchMove(body(), { cancelable: true, touches: [{ clientX: 0, clientY: 450 }] }));
      expect(sheet().style.transform).toBe("translateY(350px)");
      expect(sheet().className).toContain("dragging");
    });

    it("lets a mostly horizontal swipe go to what is under the finger", () => {
      const onChange = vi.fn();
      render(<Harness initial="half" onChange={onChange} />);
      const move = swipe(300, 340, { dx: 120 });
      expect(move.defaultPrevented).toBe(false);
      expect(onChange).not.toHaveBeenCalled();
    });

    it("does not start on an open suggestions list, so it can scroll", () => {
      const onChange = vi.fn();
      render(<Harness initial="half" onChange={onChange} />);
      const option = screen.getByRole("option", { hidden: true });
      swipe(520, 100, { target: option });
      expect(onChange).not.toHaveBeenCalled();
    });

    it("still clicks a button in the body on a tap", async () => {
      const onPress = vi.fn();
      const user = userEvent.setup();
      render(<Harness initial="half" onPress={onPress} />);
      const button = screen.getByRole("button", { name: "Press me" });
      fireEvent.touchStart(button, { touches: [{ clientX: 5, clientY: 300 }] });
      fireEvent.touchEnd(button, { changedTouches: [{ clientY: 301 }] });
      await user.click(button);
      expect(onPress).toHaveBeenCalledTimes(1);
    });

    it("swallows the click that follows a drag", () => {
      const onPress = vi.fn();
      render(<Harness initial="half" onPress={onPress} />);
      const button = screen.getByRole("button", { name: "Press me" });
      swipe(520, 100, { target: button });
      fireEvent.click(button);
      expect(onPress).not.toHaveBeenCalled();
      // Only that one click.
      fireEvent.click(button);
      expect(onPress).toHaveBeenCalledTimes(1);
    });
  });

  it("puts the page back at the top when a field in the sheet loses focus", async () => {
    const user = userEvent.setup();
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    Object.defineProperty(window, "scrollY", { value: 40, configurable: true });
    render(<Harness initial="half" />);
    await user.click(screen.getByLabelText("Search"));
    await user.tab();
    expect(scrollTo).toHaveBeenCalledWith(0, 0);
    Object.defineProperty(window, "scrollY", { value: 0, configurable: true });
    scrollTo.mockRestore();
  });

  describe("measured snaps", () => {
    function Measured({ onMeasure }: { onMeasure: (v: { peek: number; half: number }) => void }) {
      const peek = useRef<HTMLDivElement>(null);
      const half = useRef<HTMLDivElement>(null);
      return (
        <BottomSheet
          snap="peek"
          label="Search and map controls"
          onSnapChange={() => {}}
          peekRef={peek}
          halfRef={half}
          onMeasure={onMeasure}
        >
          <div ref={peek} data-testid="peek" />
          <div ref={half} data-testid="half" />
        </BottomSheet>
      );
    }

    it("ends the peek under the peek element and the middle snap under the half element", () => {
      const rect = (top: number, bottom: number) =>
        ({ top, bottom, left: 0, right: 0, width: 0, height: bottom - top, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;
      const original = Element.prototype.getBoundingClientRect;
      const offsetHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetHeight");
      Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, value: 800 });
      Element.prototype.getBoundingClientRect = function () {
        const id = (this as HTMLElement).dataset.testid;
        if (id === "peek") return rect(0, 180);
        if (id === "half") return rect(0, 560);
        return rect(0, 0);
      };
      try {
        const onMeasure = vi.fn();
        render(<Measured onMeasure={onMeasure} />);
        // Peek: 180 down to the element, plus 8 px of room. Half: 560 plus 12 px.
        expect(sheet().style.getPropertyValue("--sheet-peek")).toBe(
          "calc(188px + env(safe-area-inset-bottom, 0px))",
        );
        expect(sheet().style.getPropertyValue("--sheet-half")).toBe("572px");
        expect(onMeasure).toHaveBeenCalledWith({ peek: 188, half: 572 });
      } finally {
        Element.prototype.getBoundingClientRect = original;
        if (offsetHeight) Object.defineProperty(HTMLElement.prototype, "offsetHeight", offsetHeight);
      }
    });
  });
});
