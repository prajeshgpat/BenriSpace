import type { Metadata, Viewport } from "next";
import { Geist } from "next/font/google";

import { SiteShell } from "@/components/SiteShell";
import { SITE_DESCRIPTION, SITE_NAME, SITE_TITLE } from "@/lib/site";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: SITE_TITLE,
  description: SITE_DESCRIPTION,
  applicationName: SITE_NAME,
  // Result URLs carry the searched address; keep it out of cross-origin
  // Referer headers.
  referrer: "strict-origin-when-cross-origin",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f9f9f7" },
    { media: "(prefers-color-scheme: dark)", color: "#0d0d0d" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={geistSans.variable}>
        <SiteShell>{children}</SiteShell>
      </body>
    </html>
  );
}
