export const SITE_NAME = "BenriSpace";
export const SITE_TITLE = `${SITE_NAME} · Neighborhood convenience scores, live in the New York metro`;
export const SITE_DESCRIPTION =
  "Get a convenience score out of 100 for an address, and find where to live given where you need to be. Live now in the New York metro (parts of NY, NJ and CT), with more US metros on the way.";

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

/** The tabs on the left of the header; the logo links Home. */
export const NAV_ITEMS = [
  { href: APP_PATH, label: "Map" },
  { href: "/business", label: "For Business" },
  { href: "/docs", label: "Developers" },
  { href: "/pricing", label: "Pricing" },
] as const;

export const API_BASE_URL = "https://api.benrispace.com";
export const MCP_URL = `${API_BASE_URL}/mcp`;

/** Account controls on the far right: settings icon, then Login last. */
export const SETTINGS_ITEM = { href: "/settings", label: "Settings" } as const;
export const LOGIN_ITEM = { href: "/login", label: "Login" } as const;
