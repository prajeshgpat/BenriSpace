import type { FactorKey } from "@/lib/api/types";
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
    description: "Groceries, coffee, restaurants, the gym and a transit stop close by.",
    factors: ["grocery", "cafe", "restaurant", "gym", "transit"],
  },
  {
    id: "family",
    label: "Family",
    description: "Schools and groceries, away from noise corridors.",
    factors: ["school", "grocery", "emergencyCorridor"],
  },
  {
    id: "commuter",
    label: "Commuter",
    description: "Transit, uncongested roads and airport access.",
    factors: ["transit", "road", "airport"],
  },
  {
    id: "quiet",
    label: "Quiet",
    description:
      "Few noisy corridors, gas stations and convenience stores.",
    factors: [
      "emergencyCorridor",
      "gasStation",
      "convenienceStore",
    ],
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
