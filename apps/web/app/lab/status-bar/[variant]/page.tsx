import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { LAB_VARIANTS, STATUS_BAR_STYLE, isLabVariant } from "../variants";
import { StatusBarLab } from "./status-bar-lab";

export const dynamicParams = false;

export function generateStaticParams() {
  return LAB_VARIANTS.map((variant) => ({ variant }));
}

export async function generateMetadata({ params }: { params: Promise<{ variant: string }> }): Promise<Metadata> {
  const { variant } = await params;
  if (!isLabVariant(variant)) return {};
  return {
    title: "状态栏实验",
    manifest: `/lab/status-bar/${variant}/manifest`,
    appleWebApp: { capable: true, statusBarStyle: STATUS_BAR_STYLE[variant], title: variant === "default" ? "状态栏A" : "状态栏B" },
    robots: { index: false, follow: false },
  };
}

export default async function Page({ params }: { params: Promise<{ variant: string }> }) {
  const { variant } = await params;
  if (!isLabVariant(variant)) notFound();
  return <StatusBarLab variant={variant} />;
}
