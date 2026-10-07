/** Snap points of the mobile bottom sheet, from least to most revealed. */
export const SNAPS = ["peek", "half", "full"] as const;
export type SheetSnap = (typeof SNAPS)[number];

/** Distance (px) the sheet's top edge is pushed down from its fully open position. */
export type SnapOffsets = Record<SheetSnap, number>;

export interface PointerSample {
  /** Milliseconds, from any monotonic clock. */
  time: number;
  /** Vertical pointer position in px. */
  y: number;
}

/** A release faster than this (px per ms) is a flick, not a placement. */
export const FLICK_VELOCITY = 0.4;
/** How far ahead (ms) a moving sheet is projected before picking the nearest snap. */
export const PROJECTION_MS = 120;
/** Only samples this recent (ms) count towards the release velocity. */
export const VELOCITY_WINDOW_MS = 100;
/** A pointer that moves less than this (px) between down and up was a tap. */
export const TAP_SLOP = 6;

/** The least of the sheet (px) that stays on screen: its drag handle. */
export const MIN_VISIBLE = 40;

/** The middle snap never shows less than this share of the sheet... */
export const HALF_MIN_SHARE = 0.5;
/** ...nor more than this one, so some map always stays in view. */
export const HALF_MAX_SHARE = 0.85;

/**
 * Offsets for a sheet of `height` px of which `peekVisible` px show when
 * collapsed. At least the handle (MIN_VISIBLE px, or the whole sheet if
 * shorter) always stays on screen. The middle snap shows `halfVisible` px (what the
 * content needs to be seen in full) kept between 50% and 85% of the sheet; without a
 * measurement it shows half.
 */
export function snapOffsets(
  height: number,
  peekVisible: number,
  halfVisible?: number,
): SnapOffsets {
  const visible = Math.min(height, Math.max(peekVisible, MIN_VISIBLE));
  const peek = Math.max(0, height - visible);
  const wanted =
    halfVisible === undefined || !Number.isFinite(halfVisible)
      ? height * HALF_MIN_SHARE
      : Math.min(
          Math.max(halfVisible, height * HALF_MIN_SHARE),
          height * HALF_MAX_SHARE,
        );
  return { full: 0, half: Math.min(height - wanted, peek), peek };
}

/** Keeps a dragged offset within the sheet's travel, with no overshoot. */
export function clampOffset(offset: number, offsets: SnapOffsets): number {
  return Math.min(Math.max(offset, offsets.full), offsets.peek);
}

/** Pointer velocity in px/ms (positive is downwards) over the recent samples. */
export function releaseVelocity(samples: readonly PointerSample[]): number {
  const last = samples[samples.length - 1];
  if (!last) return 0;
  const recent = samples.filter(
    (sample) => last.time - sample.time <= VELOCITY_WINDOW_MS,
  );
  const first = recent[0];
  if (!first || last.time === first.time) return 0;
  return (last.y - first.y) / (last.time - first.time);
}

/** The snap whose offset is closest to `offset`. */
export function nearestSnap(offset: number, offsets: SnapOffsets): SheetSnap {
  let best: SheetSnap = "peek";
  for (const snap of SNAPS) {
    if (Math.abs(offsets[snap] - offset) < Math.abs(offsets[best] - offset)) {
      best = snap;
    }
  }
  return best;
}

/** One step towards `full` ("up") or `peek` ("down"); stays at the ends. */
export function stepSnap(snap: SheetSnap, direction: "up" | "down"): SheetSnap {
  const index = SNAPS.indexOf(snap) + (direction === "up" ? 1 : -1);
  return SNAPS[Math.min(Math.max(index, 0), SNAPS.length - 1)];
}

/** Enter/Space on the handle: peek, half, full, then back to peek. */
export function cycleSnap(snap: SheetSnap): SheetSnap {
  return SNAPS[(SNAPS.indexOf(snap) + 1) % SNAPS.length];
}

/**
 * Where a released drag settles. A slow drag goes to the nearest snap to where
 * the sheet was let go; a fast one is projected forward, and always moves at
 * least one snap in the direction of the flick.
 */
export function resolveSnap(input: {
  offset: number;
  velocity: number;
  offsets: SnapOffsets;
  current: SheetSnap;
}): SheetSnap {
  const { offset, velocity, offsets, current } = input;
  const flick = Math.abs(velocity) >= FLICK_VELOCITY;
  const projected = clampOffset(
    offset + (flick ? velocity * PROJECTION_MS : 0),
    offsets,
  );
  const target = nearestSnap(projected, offsets);
  if (flick && target === current) {
    return stepSnap(current, velocity < 0 ? "up" : "down");
  }
  return target;
}
