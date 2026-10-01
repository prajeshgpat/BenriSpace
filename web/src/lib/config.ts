export const DEFAULT_API_BASE_URL = "http://localhost:8000/v1";

export function resolveApiBaseUrl(value: string | undefined): string {
  const trimmed = value?.trim();
  return (trimmed || DEFAULT_API_BASE_URL).replace(/\/+$/, "");
}

// NEXT_PUBLIC_* is inlined at build time, so this must be a literal property
// access rather than a dynamic lookup.
export const API_BASE_URL = resolveApiBaseUrl(
  process.env.NEXT_PUBLIC_API_BASE_URL,
);
