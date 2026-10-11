import type { Metadata } from "next";

import { AuthForm } from "@/components/auth/AuthForm";
import { InfoPage } from "@/components/InfoPage";

export const metadata: Metadata = { title: "Login · BenriSpace" };

export default function LoginPage() {
  return (
    <InfoPage
      title="Login"
      lead="Accounts are coming soon. You do not need one to use BenriSpace today."
    >
      <AuthForm />
    </InfoPage>
  );
}
