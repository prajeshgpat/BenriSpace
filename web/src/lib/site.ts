export const SITE_NAME = "BenriSpace";
export const SITE_TITLE = `${SITE_NAME} · Convenience scores for NYC metro addresses`;
export const SITE_DESCRIPTION =
  "Score any New York metro address on everyday convenience: groceries, transit, schools, trails and more.";

export function resultTitle(address: string): string {
  return `${address} · ${SITE_NAME}`;
}

export const EXAMPLE_ADDRESSES = [
  "350 5th Ave, New York, NY",
  "Grand Central Terminal, New York, NY",
  "Hoboken Terminal, Hoboken, NJ",
  "Main St, White Plains, NY",
] as const;
