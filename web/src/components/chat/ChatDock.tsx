"use client";

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from "react";

import { ChatPanel, type ChatPanelProps } from "./ChatPanel";
import styles from "./ChatDock.module.css";

export const DOCK_STORAGE_KEY = "benrispace.chat.dock.v1";
export const DOCK_MIN = 160;
export const DOCK_DEFAULT_FRACTION = 0.45;
export const DOCK_MAX_FRACTION = 0.75;
const KEY_STEP = 24;
/** Column height assumed until the real one is measured. */
const FALLBACK_COLUMN = 800;

function loadSize(): number | null {
  try {
    const value = Number(window.sessionStorage.getItem(DOCK_STORAGE_KEY));
    return Number.isFinite(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

function saveSize(size: number) {
  try {
    window.sessionStorage.setItem(DOCK_STORAGE_KEY, String(Math.round(size)));
  } catch {
    // Not remembered; the dock still works.
  }
}

/**
 * The chat at the bottom of the desktop side column. The column's own
 * content stays above it and scrolls independently, so filters and the
 * address stay usable while chatting.
 */
export function ChatDock({
  onClose,
  onReply,
  ...panel
}: Omit<ChatPanelProps, "variant">) {
  const rootRef = useRef<HTMLElement>(null);
  const bodyId = useId();
  const [collapsed, setCollapsed] = useState(false);
  const collapsedRef = useRef(false);
  const [unread, setUnread] = useState(false);
  const [column, setColumn] = useState(0);
  const [size, setSize] = useState<number | null>(null);
  const drag = useRef<{ startY: number; startSize: number } | null>(null);

  useEffect(() => {
    setSize(loadSize());
  }, []);

  // Track the column's height so the limits are percentages of it.
  useEffect(() => {
    const parent = rootRef.current?.parentElement;
    if (!parent) return;
    const measure = () => setColumn(parent.clientHeight);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(parent);
    return () => observer.disconnect();
  }, []);

  const basis = column > 0 ? column : FALLBACK_COLUMN;
  const max = Math.max(DOCK_MIN, Math.floor(basis * DOCK_MAX_FRACTION));
  const clamp = useCallback(
    (value: number) => Math.min(max, Math.max(DOCK_MIN, value)),
    [max],
  );
  const height = clamp(size ?? Math.round(basis * DOCK_DEFAULT_FRACTION));

  function resize(next: number) {
    const value = clamp(next);
    setSize(value);
    saveSize(value);
  }

  function focusInput() {
    rootRef.current
      ?.querySelector<HTMLTextAreaElement>("textarea")
      ?.focus({ preventScroll: true });
  }

  function setCollapsedState(next: boolean) {
    collapsedRef.current = next;
    setCollapsed(next);
    if (!next) {
      setUnread(false);
      // The body is hidden until this commit lands.
      requestAnimationFrame(focusInput);
    }
  }

  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    drag.current = { startY: event.clientY, startSize: height };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  }

  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    const current = drag.current;
    if (!current) return;
    // Dragging up makes the dock taller.
    setSize(clamp(current.startSize + (current.startY - event.clientY)));
  }

  function endDrag(event: PointerEvent<HTMLDivElement>) {
    if (!drag.current) return;
    drag.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    saveSize(height);
  }

  function onHandleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    switch (event.key) {
      case "ArrowUp":
        resize(height + KEY_STEP);
        break;
      case "ArrowDown":
        resize(height - KEY_STEP);
        break;
      case "Home":
        resize(DOCK_MIN);
        break;
      case "End":
        resize(max);
        break;
      default:
        return;
    }
    event.preventDefault();
  }

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key !== "Escape" || collapsed || event.defaultPrevented) return;
    event.stopPropagation();
    setCollapsedState(true);
    rootRef.current?.querySelector<HTMLElement>("[data-dock-toggle]")?.focus();
  }

  return (
    <section
      ref={rootRef}
      className={styles.dock}
      data-collapsed={collapsed}
      aria-label="Ask BenriSpace"
      style={collapsed ? undefined : { height }}
      onKeyDown={onKeyDown}
    >
      {collapsed ? null : (
        <div
          className={styles.handle}
          role="separator"
          aria-orientation="horizontal"
          aria-label="Resize chat"
          aria-controls={bodyId}
          aria-valuenow={height}
          aria-valuemin={DOCK_MIN}
          aria-valuemax={max}
          tabIndex={0}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onKeyDown={onHandleKeyDown}
        >
          <span className={styles.grip} aria-hidden="true" />
        </div>
      )}
      <div className={styles.bar}>
        <h2 className={styles.title}>
          Ask BenriSpace
          {unread ? (
            <span className={styles.unread} role="status">
              <span className="sr-only">New reply</span>
            </span>
          ) : null}
        </h2>
        <button
          type="button"
          className={styles.barButton}
          data-dock-toggle
          aria-expanded={!collapsed}
          aria-controls={bodyId}
          onClick={() => setCollapsedState(!collapsed)}
        >
          {collapsed ? "Expand" : "Collapse"}
        </button>
        <button type="button" className={styles.barButton} onClick={onClose}>
          Close
        </button>
      </div>
      {/* Kept mounted while collapsed so a reply in flight still lands. */}
      <div id={bodyId} className={styles.body} hidden={collapsed}>
        <ChatPanel
          {...panel}
          variant="dock"
          onReply={() => {
            onReply?.();
            if (collapsedRef.current) setUnread(true);
          }}
        />
      </div>
    </section>
  );
}
