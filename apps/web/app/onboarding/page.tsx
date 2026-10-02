"use client";

import { useRouter } from "next/navigation";
import { useCallback } from "react";

import { HomePage } from "../../components/home/home-page";

// Sign-in lands here: home with the first-login taste sheet (if not done yet).
export default function OnboardingRoute() {
  const router = useRouter();
  const done = useCallback(() => router.replace("/"), [router]);
  return <HomePage onOnboardingFinished={done} />;
}
