import type { FactorKey, Score, SubScores } from "@/lib/api/types";

import {
  FACTOR_GROUPS,
  FACTOR_KEYS,
  FACTORS,
  type FactorGroup,
} from "./factors";

export const SCORE_MAX = 100;
export const NO_DATA_LABEL = "No data";

export type ScoreBand = "excellent" | "good" | "fair" | "limited";

const BAND_LABELS: Record<ScoreBand, string> = {
  excellent: "Excellent",
  good: "Good",
  fair: "Fair",
  limited: "Limited",
};

export function clampScore(value: number): number {
  return Math.min(SCORE_MAX, Math.max(0, value));
}

export function roundScore(value: number): number {
  return Math.round(clampScore(value));
}

export function scoreBand(value: number): ScoreBand {
  const score = roundScore(value);
  if (score >= 80) return "excellent";
  if (score >= 60) return "good";
  if (score >= 40) return "fair";
  return "limited";
}

export function bandLabel(value: number): string {
  return BAND_LABELS[scoreBand(value)];
}

export interface FactorRow {
  key: FactorKey;
  label: string;
  description: string;
  /** Rounded 0-100 value, or `null` when the API has no data for the factor. */
  value: number | null;
  display: string;
  band: string | null;
}

export interface FactorSection {
  group: FactorGroup;
  title: string;
  rows: FactorRow[];
}

function toFactorRow(key: FactorKey, raw: number | null): FactorRow {
  const { label, description } = FACTORS[key];
  if (raw === null) {
    return { key, label, description, value: null, display: NO_DATA_LABEL, band: null };
  }
  const value = roundScore(raw);
  return { key, label, description, value, display: String(value), band: bandLabel(raw) };
}

export function buildFactorSections(subScores: SubScores): FactorSection[] {
  return (Object.keys(FACTOR_GROUPS) as FactorGroup[]).map((group) => ({
    group,
    title: FACTOR_GROUPS[group],
    rows: FACTOR_KEYS.filter((key) => FACTORS[key].group === group).map((key) =>
      toFactorRow(key, subScores[key]),
    ),
  }));
}

export interface Coverage {
  available: number;
  total: number;
  isComplete: boolean;
  summary: string;
}

export function summarizeCoverage(subScores: SubScores): Coverage {
  const total = FACTOR_KEYS.length;
  const available = FACTOR_KEYS.filter((key) => subScores[key] !== null).length;
  const isComplete = available === total;

  let summary: string;
  if (isComplete) {
    summary = `Based on all ${total} factors.`;
  } else if (available === 0) {
    summary = "No factor breakdown is available for this area yet.";
  } else {
    summary = `Based on ${available} of ${total} factors. The rest have no data for this area yet, so this score may change.`;
  }
  return { available, total, isComplete, summary };
}

const COORDINATE_PAIR = /^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/;

export function isCoordinateAddress(address: string): boolean {
  return COORDINATE_PAIR.test(address);
}

export function formatCoordinates(latitude: number, longitude: number): string {
  const lat = `${Math.abs(latitude).toFixed(4)}° ${latitude >= 0 ? "N" : "S"}`;
  const lon = `${Math.abs(longitude).toFixed(4)}° ${longitude >= 0 ? "E" : "W"}`;
  return `${lat}, ${lon}`;
}

/**
 * The backend scores grid cells and does not reverse-geocode yet, so
 * `score.address` is often just "lat,lon". Say which area was scored without
 * presenting that string as though it were a street address.
 */
export function describeScoredLocation(
  score: Pick<Score, "address" | "latitude" | "longitude">,
  /** A reverse-geocoded street address for the point, when one is known. */
  readableAddress: string | null = null,
): string {
  const coordinates = formatCoordinates(score.latitude, score.longitude);
  const address = score.address.trim();
  if (address === "" || isCoordinateAddress(address)) {
    return readableAddress
      ? `Scored for the area around ${readableAddress}`
      : `Scored for the area around ${coordinates}`;
  }
  return `Scored for ${address} (${coordinates})`;
}

export function formatComputedAt(
  iso: string,
  { locale = "en-US", timeZone }: { locale?: string; timeZone?: string } = {},
): string | null {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeZone,
  }).format(date);
}
