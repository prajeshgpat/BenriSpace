import type { Metadata } from "next";

import { InfoPage } from "@/components/InfoPage";
import { ThemeSettings } from "@/components/ThemeSettings";

export const metadata: Metadata = { title: "Settings · BenriSpace" };

export default function SettingsPage() {
  return (
    <InfoPage title="Settings" lead="Preferences are saved in this browser.">
      <ThemeSettings />
    </InfoPage>
  );
}
