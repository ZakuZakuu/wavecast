import type { Metadata } from "next";

import { ViewportLab } from "./viewport-lab";

export const metadata: Metadata = {
  title: "视口诊断",
  manifest: "/lab/viewport/manifest",
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: "视口诊断" },
  robots: { index: false, follow: false },
};

export default function Page() {
  return <ViewportLab />;
}
