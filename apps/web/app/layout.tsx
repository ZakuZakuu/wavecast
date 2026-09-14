import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Wavecast",
  description: "Guided listening that starts with music.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
