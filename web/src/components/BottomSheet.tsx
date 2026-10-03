"use client";

import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
  type Ref,
} from "react";

import {
  TAP_SLOP,
  clampOffset,
  cycleSnap,
  releaseVelocity,
  resolveSnap,
  snapOffsets,
  stepSnap,
  type PointerSample,
  type SheetSnap,
  type SnapOffsets,
} from "@/lib/sheetSnap";

import styles from "./BottomSheet.module.css";

interface BottomSheetProps {
  snap: SheetSnap;
  onSnapChange: (snap: SheetSnap) => void;
  /** Accessible name of the sheet region. */
  label: string;
  children: ReactNode;
  ref?: Ref<HTMLElement>;
}

interface Drag {
  pointerId: number;
  startY: number;
  startOffset: number;
  offsets: SnapOffsets;
  samples: PointerSample[];
  moved: boolean;
}

/**
 * A draggable panel over the bottom of its positioned parent, with three
 * snap points. The handle drags; the body scrolls when fully open, and a downward swipe
 * from its top edge pulls the sheet back down.
 */
export function BottomSheet({
  snap,
  onSnapChange,
  label,
  children,
  ref,
}: BottomSheetProps) {
  const bodyId = useId();
  const sheetRef = useRef<HTMLElement | null>(null);
  const peekRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const latest = useRef({ snap, onSnapChange });
  useEffect(() => {
    latest.current = { snap, onSnapChange };
  });
  const suppressClick = useRef(false);
  // Pixels the sheet is pulled down from fully open, while a finger is on it.
  const [dragOffset, setDragOffset] = useState<number | null>(null);

  function setSheet(node: HTMLElement | null) {
    sheetRef.current = node;
    if (typeof ref === "function") ref(node);
    else if (ref) ref.current = node;
  }

  function handlePointerDown(event: PointerEvent<HTMLButtonElement>) {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const sheet = sheetRef.current;
    if (!sheet) return;
    suppressClick.current = false;
    const offsets = snapOffsets(
      sheet.offsetHeight,
      peekRef.current?.offsetHeight ?? 0,
    );
    drag.current = {
      pointerId: event.pointerId,
      startY: event.clientY,
      startOffset: offsets[snap],
      offsets,
      samples: [{ time: event.timeStamp, y: event.clientY }],
      moved: false,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function handlePointerMove(event: PointerEvent<HTMLButtonElement>) {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    const delta = event.clientY - current.startY;
    if (!current.moved && Math.abs(delta) < TAP_SLOP) return;
    current.moved = true;
    current.samples.push({ time: event.timeStamp, y: event.clientY });
    if (current.samples.length > 12) current.samples.shift();
    setDragOffset(clampOffset(current.startOffset + delta, current.offsets));
  }

  function finishDrag(event: PointerEvent<HTMLButtonElement>, commit: boolean) {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    drag.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    if (!current.moved) return;
    suppressClick.current = true;
    setDragOffset(null);
    if (!commit) return;
    const offset = clampOffset(
      current.startOffset + event.clientY - current.startY,
      current.offsets,
    );
    onSnapChange(
      resolveSnap({
        offset,
        velocity: releaseVelocity(current.samples),
        offsets: current.offsets,
        current: snap,
      }),
    );
  }

  // A downward swipe that starts in the body of the fully open sheet while it
  // is scrolled to the top pulls the sheet down. Anything else scrolls as usual.
  // Native listeners: React's touchmove is passive and cannot stop the scroll.
  useEffect(() => {
    const body = bodyRef.current;
    if (!body) return;
    let gesture: Drag | null = null;

    function onTouchStart(event: TouchEvent) {
      gesture = null;
      const sheet = sheetRef.current;
      const touch = event.touches[0];
      if (!sheet || !touch || event.touches.length !== 1) return;
      if (latest.current.snap !== "full" || body!.scrollTop > 0) return;
      const offsets = snapOffsets(
        sheet.offsetHeight,
        peekRef.current?.offsetHeight ?? 0,
      );
      gesture = {
        pointerId: 0,
        startY: touch.clientY,
        startOffset: offsets.full,
        offsets,
        samples: [{ time: event.timeStamp, y: touch.clientY }],
        moved: false,
      };
    }

    function onTouchMove(event: TouchEvent) {
      const touch = event.touches[0];
      if (!gesture || !touch) return;
      const delta = touch.clientY - gesture.startY;
      if (!gesture.moved) {
        if (delta < 0 || body!.scrollTop > 0) {
          gesture = null; // scrolling up, or already scrolled: plain scroll
          return;
        }
        if (delta < TAP_SLOP) return;
        gesture.moved = true;
      }
      event.preventDefault();
      gesture.samples.push({ time: event.timeStamp, y: touch.clientY });
      if (gesture.samples.length > 12) gesture.samples.shift();
      setDragOffset(clampOffset(gesture.startOffset + delta, gesture.offsets));
    }

    function onTouchEnd(event: TouchEvent, commit: boolean) {
      const current = gesture;
      gesture = null;
      if (!current?.moved) return;
      setDragOffset(null);
      if (!commit) return;
      const end = event.changedTouches[0]?.clientY ?? current.startY;
      const offset = clampOffset(
        current.startOffset + end - current.startY,
        current.offsets,
      );
      latest.current.onSnapChange(
        resolveSnap({
          offset,
          velocity: releaseVelocity(current.samples),
          offsets: current.offsets,
          current: latest.current.snap,
        }),
      );
    }

    const end = (event: TouchEvent) => onTouchEnd(event, true);
    const cancel = (event: TouchEvent) => onTouchEnd(event, false);
    body.addEventListener("touchstart", onTouchStart, { passive: true });
    body.addEventListener("touchmove", onTouchMove, { passive: false });
    body.addEventListener("touchend", end);
    body.addEventListener("touchcancel", cancel);
    return () => {
      body.removeEventListener("touchstart", onTouchStart);
      body.removeEventListener("touchmove", onTouchMove);
      body.removeEventListener("touchend", end);
      body.removeEventListener("touchcancel", cancel);
    };
  }, []);

  function handleClick() {
    if (suppressClick.current) {
      suppressClick.current = false;
      return;
    }
    onSnapChange(cycleSnap(snap));
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    event.preventDefault();
    onSnapChange(stepSnap(snap, event.key === "ArrowUp" ? "up" : "down"));
  }

  return (
    <aside
      ref={setSheet}
      className={`${styles.sheet} ${dragOffset !== null ? styles.dragging : ""}`}
      data-snap={snap}
      aria-label={label}
      tabIndex={-1}
      style={
        dragOffset !== null
          ? { transform: `translateY(${dragOffset}px)` }
          : undefined
      }
    >
      <div ref={peekRef} className={styles.peekProbe} aria-hidden="true" />
      <button
        type="button"
        className={styles.handle}
        aria-label="Resize results panel"
        aria-controls={bodyId}
        aria-expanded={snap !== "peek"}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={(event) => finishDrag(event, true)}
        onPointerCancel={(event) => finishDrag(event, false)}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
      >
        <span className={styles.grip} aria-hidden="true" />
      </button>
      <div
        id={bodyId}
        ref={bodyRef}
        className={styles.body}
        // Content below the fold is out of sight until the sheet opens, so
        // tabbing into it opens the sheet rather than focusing something hidden.
        onFocusCapture={() => {
          if (snap === "peek") onSnapChange("half");
        }}
      >
        {children}
      </div>
    </aside>
  );
}
