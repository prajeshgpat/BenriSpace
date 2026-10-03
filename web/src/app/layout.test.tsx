import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/font/google", () => ({
  Geist: () => ({ variable: "font-geist" }),
}));
vi.mock("@/components/SiteShell", () => ({
  SiteShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import RootLayout from "./layout";

describe("RootLayout", () => {
  it("declares English and opts out of browser translation", () => {
    const html = renderToStaticMarkup(<RootLayout>x</RootLayout>);
    expect(html).toMatch(/<html[^>]*lang="en"/);
    expect(html).toMatch(/<html[^>]*translate="no"/);
    expect(html).toContain('<meta name="google" content="notranslate"/>');
  });
});
