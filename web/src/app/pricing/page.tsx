import type { Metadata } from "next";

import { InfoPage } from "@/components/InfoPage";
import { PricingFaq } from "@/components/pricing/PricingFaq";
import { PricingTiers } from "@/components/pricing/PricingTiers";

export const metadata: Metadata = { title: "Pricing · BenriSpace" };

export default function PricingPage() {
  return (
    <InfoPage
      title="Pricing"
      lead="BenriSpace is free while it is in beta. Prices below are placeholders and are not final."
    >
      <PricingTiers />
      <PricingFaq />
    </InfoPage>
  );
}
