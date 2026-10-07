import type { Metadata, Viewport } from "next";

import { LibraryIdentityBridge } from "../components/library-identity-bridge";
import { BrowserGuidance } from "../components/browser-guidance";
import { DesktopStage } from "../components/desktop-stage";
import { GlobalChrome } from "../components/global-chrome";
import { KeyboardShortcuts } from "../components/keyboard-shortcuts";
import { PlaybackProvider } from "../components/player/playback-provider";
import { PlayerOverlay } from "../components/player/player-overlay";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/player.css";
import "./styles/tune.css";
import "./styles/home.css";
import "./styles/overlays.css";
import "./styles/account.css";
import "./styles/desktop.css";

export const metadata: Metadata = {
  title: "WaveCast",
  description: "轻主持的 AI 音乐电台。",
  applicationName: "WaveCast",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "WaveCast",
  },
  icons: {
    icon: [{ url: "/icon.svg", type: "image/svg+xml" }],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180" }],
  },
  formatDetection: {
    telephone: false,
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#F2F2F4",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <LibraryIdentityBridge>
          <PlaybackProvider>
            <DesktopStage />
            <KeyboardShortcuts />
            <div className="app-root">
              {children}
              <PlayerOverlay />
              <GlobalChrome />
              <BrowserGuidance />
            </div>
          </PlaybackProvider>
        </LibraryIdentityBridge>
      </body>
    </html>
  );
}
