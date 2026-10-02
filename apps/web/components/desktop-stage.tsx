"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { qrPath, type QrPath } from "../lib/qr";
import { stationById } from "../lib/stations";
import { LogoMark } from "./logo-mark";
import { useNowPlaying } from "./player/playback-provider";

/**
 * Wide screens (≥ 768px): the app stays a centred 430px column; behind it a
 * designed backdrop whose glows follow the current station, and (≥ 1100px) a
 * side card with a QR code of the current address. Hidden on phones by CSS.
 */
export function DesktopStage() {
  const np = useNowPlaying();
  const station = np?.station ?? stationById("casual");
  return (
    <>
      <div className="desk-backdrop" aria-hidden="true">
        <span className="desk-glow desk-glow-a" style={{ backgroundColor: station.light }} />
        <span className="desk-glow desk-glow-b" style={{ backgroundColor: station.deep }} />
        <span className="desk-glow desk-glow-c" style={{ backgroundColor: station.light }} />
      </div>
      <DesktopSideCard />
    </>
  );
}

function DesktopSideCard() {
  const pathname = usePathname();
  const [qr, setQr] = useState<QrPath | null>(null);

  // The current address (client only), refreshed as the route changes.
  useEffect(() => {
    if (!window.matchMedia?.("(min-width: 1100px)").matches) return;
    try {
      setQr(qrPath(window.location.href));
    } catch {
      setQr(null);
    }
  }, [pathname]);

  const quiet = 2;
  return (
    <aside className="desk-card" aria-label="在手机上打开">
      <span className="desk-card-logo"><LogoMark size={56} /></span>
      <h2 className="desk-card-name">WaveCast</h2>
      <p className="desk-card-line">轻主持的 AI 音乐电台</p>
      <span className="desk-qr">
        {qr ? (
          <svg
            viewBox={`${-quiet} ${-quiet} ${qr.size + quiet * 2} ${qr.size + quiet * 2}`}
            shapeRendering="crispEdges"
            role="img"
            aria-label="当前网址的二维码"
          >
            <rect x={-quiet} y={-quiet} width={qr.size + quiet * 2} height={qr.size + quiet * 2} fill="#FFFFFF" />
            <path d={qr.d} fill="#1D1D1F" />
          </svg>
        ) : null}
      </span>
      <p className="desk-card-foot">用手机扫码打开，可以添加到主屏幕</p>
    </aside>
  );
}
