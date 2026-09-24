import type { Metadata, Viewport } from "next";

import "./styles.css";

export const metadata: Metadata = {
  title: "WaveCast",
  description: "AI-native guided listening radio.",
  applicationName: "WaveCast",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "WaveCast",
  },
  formatDetection: {
    telephone: false,
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f6f2" },
    { media: "(prefers-color-scheme: dark)", color: "#0b0c0f" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
