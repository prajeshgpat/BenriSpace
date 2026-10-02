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

/** The split-screen app. `/` is the static home page. */
export const APP_PATH = "/app";

/** The tabs on the left of the header. */
export const NAV_ITEMS = [
  { href: "/", label: "Home" },
  { href: APP_PATH, label: "App" },
  { href: "/docs", label: "API" },
  { href: "/pricing", label: "Pricing" },
] as const;

/** Account controls on the far right: settings icon, then Login last. */
export const SETTINGS_ITEM = { href: "/settings", label: "Settings" } as const;
export const LOGIN_ITEM = { href: "/login", label: "Login" } as const;
