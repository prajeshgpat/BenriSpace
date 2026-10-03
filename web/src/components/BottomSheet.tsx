"use client";

import {
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
 * snap points. Only the handle drags; the body scrolls when fully open.
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
  const drag = useRef<Drag | null>(null);
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
