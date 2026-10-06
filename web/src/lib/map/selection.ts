import type { FactorKey, PriorityQuery } from "@/lib/api/types";
import { FACTOR_KEYS } from "@/lib/score/factors";

export type Importance = "low" | "normal" | "high";

export const IMPORTANCE_LEVELS: readonly Importance[] = [
  "low",
  "normal",
  "high",
];

/**
 * The API takes absolute weights, so importance is a multiple of the server's
 * default for that factor rather than a number the UI invents.
 */
export const IMPORTANCE_MULTIPLIER: Record<Importance, number> = {
  low: 0.5,
  normal: 1,
  high: 2,
};

export type ImportanceOverrides = Partial<
  Record<FactorKey, Exclude<Importance, "normal">>
>;

export interface FactorSelection {
  /** In canonical `FACTOR_KEYS` order, so equal selections compare equal. */
  factors: readonly FactorKey[];
  importance: ImportanceOverrides;
}

export type DefaultWeights = Partial<Record<FactorKey, number>>;

function canonical(factors: Iterable<FactorKey>): FactorKey[] {
  const set = new Set(factors);
  return FACTOR_KEYS.filter((key) => set.has(key));
}

export function createSelection(
  factors: Iterable<FactorKey>,
  importance: ImportanceOverrides = {},
): FactorSelection {
  const list = canonical(factors);
  return {
    factors: list,
    importance: Object.fromEntries(
      Object.entries(importance).filter(([key]) =>
        list.includes(key as FactorKey),
      ),
    ),
  };
}

export const ALL_FACTORS: FactorSelection = createSelection(FACTOR_KEYS);

/** Off when the app opens: the everyday-errands factors stay on, the rest are opt-in. */
const OFF_BY_DEFAULT: ReadonlySet<FactorKey> = new Set<FactorKey>([
  "shopping",
  "airport",
  "gasConvenience",
  "traffic",
  "school",
  "emergencyCorridor",
]);

/** The factors switched on when the app opens without a `factors` link parameter. */
export const DEFAULT_FACTOR_KEYS: readonly FactorKey[] = FACTOR_KEYS.filter(
  (key) => !OFF_BY_DEFAULT.has(key),
);

export const DEFAULT_SELECTION: FactorSelection = createSelection(DEFAULT_FACTOR_KEYS);

export function isDefaultSelection(selection: FactorSelection): boolean {
  return (
    selection.factors.length === DEFAULT_FACTOR_KEYS.length &&
    DEFAULT_FACTOR_KEYS.every((key) => selection.factors.includes(key))
  );
}

export function isAllSelected(selection: FactorSelection): boolean {
  return selection.factors.length === FACTOR_KEYS.length;
}

export function toggleFactor(
  selection: FactorSelection,
  key: FactorKey,
): FactorSelection {
  const next = selection.factors.includes(key)
    ? selection.factors.filter((k) => k !== key)
    : [...selection.factors, key];
  return createSelection(next, selection.importance);
}

export function setImportance(
  selection: FactorSelection,
  key: FactorKey,
  level: Importance,
): FactorSelection {
  const rest = Object.fromEntries(
    Object.entries(selection.importance).filter(([k]) => k !== key),
  );
  return createSelection(
    selection.factors,
    level === "normal" ? rest : { ...rest, [key]: level },
  );
}

export function importanceOf(
  selection: FactorSelection,
  key: FactorKey,
): Importance {
  return selection.importance[key] ?? "normal";
}

export interface Preset {
  id: string;
  label: string;
  /** Why these factors, shown as the button's tooltip. */
  description: string;
  factors: readonly FactorKey[];
}

export const PRESETS: readonly Preset[] = [
  {
    id: "errands",
    label: "Daily errands",
    description:
      "Groceries, restaurants, coffee, the gym, shopping and a transit stop close by.",
    factors: ["grocery", "restaurant", "cafe", "gym", "shopping", "transit"],
  },
  {
    id: "family",
    label: "Family",
    description: "Schools, groceries and parks, away from noise corridors.",
    factors: ["school", "grocery", "recreation", "emergencyCorridor"],
  },
  {
    id: "commuter",
    label: "Commuter",
    description: "Transit, gas and convenience stops, light traffic and airport access.",
    factors: ["transit", "gasConvenience", "traffic", "airport"],
  },
  {
    id: "quiet",
    label: "Quiet",
    description: "Away from noise corridors and busy roads.",
    factors: ["emergencyCorridor", "traffic"],
  },
];

export function applyPreset(preset: Preset): FactorSelection {
  return createSelection(preset.factors);
}

/** The preset the selection matches exactly (with default importance), if any. */
export function activePresetId(selection: FactorSelection): string | null {
  if (Object.keys(selection.importance).length > 0) return null;
  const match = PRESETS.find(
    (preset) =>
      preset.factors.length === selection.factors.length &&
      preset.factors.every((key) => selection.factors.includes(key)),
  );
  return match?.id ?? null;
}

/**
 * Absolute weights for the factors that have a non-default importance, or
 * `undefined` when there is nothing to override. A factor whose default is not
 * known yet is skipped; the response then reveals the default and this runs
 * again.
 */
export function resolveWeights(
  selection: FactorSelection,
  defaults: DefaultWeights,
): DefaultWeights | undefined {
  const entries = selection.factors.flatMap((key): [FactorKey, number][] => {
    const base = defaults[key];
    const level = selection.importance[key];
    if (base === undefined || level === undefined) return [];
    return [
      [key, Math.round(base * IMPORTANCE_MULTIPLIER[level] * 1000) / 1000],
    ];
  });
  return entries.length > 0 ? Object.fromEntries(entries) : undefined;
}

/**
 * Folds a response's `weights` into the known defaults. Only factors that were
 * not overridden in the request count: for those the response echoes the
 * server's own default.
 */
export function learnDefaults(
  known: DefaultWeights,
  responseWeights: Record<string, number>,
  overridden: DefaultWeights | undefined,
): DefaultWeights {
  let next = known;
  for (const key of FACTOR_KEYS) {
    const value = responseWeights[key];
    if (value === undefined || value <= 0) continue;
    if (overridden?.[key] !== undefined) continue;
    if (next[key] === value) continue;
    if (next === known) next = { ...known };
    next[key] = value;
  }
  return next;
}

/**
 * The selection as the priority endpoints (`/improve`, `/similar`, the
 * explanations) and the map endpoints take it. `factors` is left out when all
 * are selected, which the API reads as "everything".
 */
export function priorityQuery(
  selection: FactorSelection,
  weights: DefaultWeights | undefined,
): PriorityQuery {
  return {
    factors: isAllSelected(selection) ? undefined : selection.factors,
    weights,
  };
}

/** A string identity for a priorities query, for effect keys and debouncing. */
export function priorityKey(query: PriorityQuery): string {
  const weights = Object.entries(query.weights ?? {}).sort(([a], [b]) =>
    a < b ? -1 : 1,
  );
  return `${query.factors ? query.factors.join(",") : "*"}|${JSON.stringify(weights)}`;
}

/** An explicit empty list is "no factors": the API rejects it, so callers skip the request. */
export function hasNoFactors(query: PriorityQuery): boolean {
  return query.factors !== undefined && query.factors.length === 0;
}
