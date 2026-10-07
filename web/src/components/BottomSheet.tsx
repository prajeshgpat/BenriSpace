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
  type RefObject,
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
  /**
   * The element whose bottom edge ends the collapsed sheet (the handle and the controls
   * above it stay visible). Without it, or before it is laid out, the peek is a fixed 6rem.
   */
  peekRef?: RefObject<HTMLElement | null>;
  /**
   * The element whose bottom edge ends the middle snap, so everything down to it is in
   * view (clamped between half and 85% of the sheet). Without it the middle snap is half.
   */
  halfRef?: RefObject<HTMLElement | null>;
  /** The visible height (px, excluding the bottom safe area) at peek and half, once measured. */
  onMeasure?: (visible: { peek: number; half: number }) => void;
}

/** A click this soon (ms) after a drag ended is the drag's own, not a tap. */
const CLICK_AFTER_DRAG_MS = 500;

/** Room under the peek element, and under the half element. */
const PEEK_PADDING = 8;
const HALF_PADDING = 12;

interface TouchGesture extends Drag {
  startX: number;
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
  peekRef,
  halfRef,
  onMeasure,
}: BottomSheetProps) {
  const bodyId = useId();
  const sheetRef = useRef<HTMLElement | null>(null);
  const probeRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const latest = useRef({ snap, onSnapChange, peekRef, halfRef, onMeasure });
  useEffect(() => {
    latest.current = { snap, onSnapChange, peekRef, halfRef, onMeasure };
  });
  const suppressClick = useRef(false);
  // When a finger last lifted after dragging the body; the click that follows is not a tap.
  const bodyDragEnded = useRef(Number.NEGATIVE_INFINITY);
  // Visible px at the middle snap, once its element has been measured.
  const halfVisible = useRef<number | undefined>(undefined);
  const observer = useRef<ResizeObserver | null>(null);
  const lastMeasure = useRef({ peek: NaN, half: NaN });
  // Pixels the sheet is pulled down from fully open, while a finger is on it.
  const [dragOffset, setDragOffset] = useState<number | null>(null);

  function setSheet(node: HTMLElement | null) {
    sheetRef.current = node;
    if (typeof ref === "function") ref(node);
    else if (ref) ref.current = node;
  }

  function currentOffsets(sheet: HTMLElement): SnapOffsets {
    return snapOffsets(
      sheet.offsetHeight,
      probeRef.current?.offsetHeight ?? 0,
      halfVisible.current,
    );
  }

  // The peek and middle snaps follow the content: the peek ends under the search box and
  // the point-of-interest pills, the middle snap under the score card (or the overlap
  // results). Re-measured after every render and whenever any of those boxes resizes.
  useEffect(() => {
    const sheet = sheetRef.current;
    const body = bodyRef.current;
    if (!sheet || !body) return;

    function measure() {
      const sheet = sheetRef.current;
      const body = bodyRef.current;
      if (!sheet || !body) return;
      const top = sheet.getBoundingClientRect().top;
      const bottomOf = (element: HTMLElement | null | undefined) =>
        element ? element.getBoundingClientRect().bottom - top + body.scrollTop : 0;

      const peekBottom = bottomOf(latest.current.peekRef?.current);
      // jsdom, or an element that is not laid out yet: keep the CSS default.
      const peek = peekBottom > 0 ? peekBottom + PEEK_PADDING : NaN;
      if (Number.isNaN(peek)) sheet.style.removeProperty("--sheet-peek");
      else {
        sheet.style.setProperty(
          "--sheet-peek",
          `calc(${peek}px + env(safe-area-inset-bottom, 0px))`,
        );
      }

      const halfBottom = bottomOf(latest.current.halfRef?.current);
      halfVisible.current = halfBottom > 0 ? halfBottom + HALF_PADDING : undefined;
      const height = sheet.offsetHeight;
      const offsets = snapOffsets(
        height,
        Number.isNaN(peek) ? 0 : peek,
        halfVisible.current,
      );
      const half = height - offsets.half;
      if (height > 0) {
        sheet.style.setProperty("--sheet-half", `${half}px`);
      } else sheet.style.removeProperty("--sheet-half");

      const visiblePeek = Number.isNaN(peek) ? NaN : height - offsets.peek;
      if (
        latest.current.onMeasure &&
        height > 0 &&
        (lastMeasure.current.peek !== visiblePeek || lastMeasure.current.half !== half)
      ) {
        lastMeasure.current = { peek: visiblePeek, half };
        latest.current.onMeasure({ peek: visiblePeek, half });
      }
    }

    measure();
    if (typeof ResizeObserver === "undefined") return;
    // The measured elements come and go with the content, so watch whichever exist now.
    observer.current ??= new ResizeObserver(measure);
    observer.current.disconnect();
    observer.current.observe(sheet);
    observer.current.observe(body);
    for (const element of [peekRef?.current, halfRef?.current]) {
      if (element) observer.current.observe(element);
    }
  });
  useEffect(() => () => observer.current?.disconnect(), []);

  function handlePointerDown(event: PointerEvent<HTMLButtonElement>) {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const sheet = sheetRef.current;
    if (!sheet) return;
    suppressClick.current = false;
    const offsets = currentOffsets(sheet);
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

  // A vertical drag that starts anywhere in the body moves the sheet, so it can be pulled
  // from the content and not only from the handle. At peek and half the body does not
  // scroll, so any vertical drag moves the sheet (up opens it, down closes it). On the fully
  // open sheet a downward drag from the top of the scrolled content pulls it down; every
  // other drag there scrolls. A drag that turns out to be horizontal is left to whatever
  // is under the finger (a scroller, a text field). Native listeners: React's touchmove is
  // passive and cannot stop the scroll.
  useEffect(() => {
    const body = bodyRef.current;
    if (!body) return;
    let gesture: TouchGesture | null = null;

    function onTouchStart(event: TouchEvent) {
      gesture = null;
      bodyDragEnded.current = Number.NEGATIVE_INFINITY;
      const sheet = sheetRef.current;
      const touch = event.touches[0];
      if (!sheet || !touch || event.touches.length !== 1) return;
      const origin = event.target instanceof Element ? event.target : null;
      // Suggestions scroll on their own.
      if (origin?.closest("[role=listbox]:not([hidden])")) return;
      const current = latest.current.snap;
      if (current === "full" && body!.scrollTop > 0) return;
      const offsets = currentOffsets(sheet);
      gesture = {
        pointerId: 0,
        startX: touch.clientX ?? 0,
        startY: touch.clientY,
        startOffset: offsets[current],
        offsets,
        samples: [{ time: event.timeStamp, y: touch.clientY }],
        moved: false,
      };
    }

    function onTouchMove(event: TouchEvent) {
      const touch = event.touches[0];
      if (!gesture || !touch) return;
      const dy = touch.clientY - gesture.startY;
      if (!gesture.moved) {
        const dx = (touch.clientX ?? 0) - gesture.startX;
        if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) >= TAP_SLOP) {
          gesture = null; // horizontal: not ours
          return;
        }
        if (latest.current.snap === "full" && (dy < 0 || body!.scrollTop > 0)) {
          gesture = null; // scrolling the content
          return;
        }
        if (Math.abs(dy) < TAP_SLOP) return;
        gesture.moved = true;
      }
      event.preventDefault();
      gesture.samples.push({ time: event.timeStamp, y: touch.clientY });
      if (gesture.samples.length > 12) gesture.samples.shift();
      setDragOffset(clampOffset(gesture.startOffset + dy, gesture.offsets));
    }

    function onTouchEnd(event: TouchEvent, commit: boolean) {
      const current = gesture;
      gesture = null;
      if (!current?.moved) return;
      bodyDragEnded.current = performance.now();
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

    // The click a browser may still send after a drag must not press whatever was under it.
    function onClickCapture(event: MouseEvent) {
      if (performance.now() - bodyDragEnded.current < CLICK_AFTER_DRAG_MS) {
        bodyDragEnded.current = Number.NEGATIVE_INFINITY;
        event.preventDefault();
        event.stopPropagation();
      }
    }

    const end = (event: TouchEvent) => onTouchEnd(event, true);
    const cancel = (event: TouchEvent) => onTouchEnd(event, false);
    body.addEventListener("touchstart", onTouchStart, { passive: true });
    body.addEventListener("touchmove", onTouchMove, { passive: false });
    body.addEventListener("touchend", end);
    body.addEventListener("touchcancel", cancel);
    body.addEventListener("click", onClickCapture, true);
    return () => {
      body.removeEventListener("touchstart", onTouchStart);
      body.removeEventListener("touchmove", onTouchMove);
      body.removeEventListener("touchend", end);
      body.removeEventListener("touchcancel", cancel);
      body.removeEventListener("click", onClickCapture, true);
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
      <div ref={probeRef} className={styles.peekProbe} aria-hidden="true" />
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
        // The keyboard closing can leave the page scrolled, with the sheet's top under the
        // browser's bar; put it back.
        onBlurCapture={(event) => {
          if (
            event.target instanceof HTMLInputElement ||
            event.target instanceof HTMLTextAreaElement
          ) {
            if (window.scrollY !== 0) window.scrollTo(0, 0);
          }
        }}
      >
        {children}
      </div>
    </aside>
  );
}
