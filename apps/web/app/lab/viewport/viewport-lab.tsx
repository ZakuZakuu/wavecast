"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";

const STRATEGIES = {
  a: { label: "a 100dvh（现状）", style: { top: 0, height: "100dvh" } },
  b: { label: "b 100dvh+顶部安全区", style: { top: 0, height: "calc(100dvh + env(safe-area-inset-top, 0px))" } },
  c: { label: "c 100lvh", style: { top: 0, height: "100lvh" } },
  d: { label: "d screen.height", style: { top: 0, height: "var(--screen-h)" } },
  e: { label: "e bottom 负顶部安全区", style: { top: 0, bottom: "calc(-1 * env(safe-area-inset-top, 0px))" } },
  f: { label: "f fixed inset 0", style: { position: "fixed", top: 0, bottom: 0 } },
} as const satisfies Record<string, { label: string; style: CSSProperties }>;
type Strategy = keyof typeof STRATEGIES;

interface Reading { label: string; value: string }

/** Temporary: read the real viewport numbers on an iPhone and try fixes live. */
export function ViewportLab() {
  const probes = useRef<HTMLDivElement>(null);
  const [strategy, setStrategy] = useState<Strategy>("a");
  const [rows, setRows] = useState<Reading[]>([]);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    const measure = () => {
      const box = (css: string) => {
        const el = document.createElement("div");
        el.style.cssText = `position:absolute;visibility:hidden;pointer-events:none;${css}`;
        probes.current?.append(el);
        const rect = el.getBoundingClientRect();
        el.remove();
        return rect;
      };
      const px = (n: number) => `${Math.round(n * 10) / 10}`;
      const vv = window.visualViewport;
      setRows([
        { label: "standalone", value: String((navigator as Navigator & { standalone?: boolean }).standalone ?? window.matchMedia("(display-mode: standalone)").matches) },
        { label: "screen.height", value: px(screen.height) },
        { label: "window.innerHeight", value: px(window.innerHeight) },
        { label: "documentElement.clientHeight", value: px(document.documentElement.clientHeight) },
        { label: "visualViewport.height", value: vv ? px(vv.height) : "-" },
        { label: "100dvh / 100svh / 100lvh", value: [box("height:100dvh"), box("height:100svh"), box("height:100lvh")].map((r) => px(r.height)).join(" / ") },
        { label: "safe-area top / bottom", value: [box("height:env(safe-area-inset-top,0px)"), box("height:env(safe-area-inset-bottom,0px)")].map((r) => px(r.height)).join(" / ") },
        { label: ".app-root 高度", value: px(document.querySelector(".app-root")?.getBoundingClientRect().height ?? 0) },
      ]);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  const chosen = STRATEGIES[strategy];
  const layer = (
    <div
      style={{
        position: "absolute", left: 0, right: 0, zIndex: 9999, display: "flex", flexDirection: "column",
        background: "#17143A", color: "#fff", outline: "3px solid #ff3b30", outlineOffset: "-3px",
        ["--screen-h" as string]: `${screen.height}px`, ...chosen.style,
      } as CSSProperties}
    >
      <div style={{ padding: "calc(env(safe-area-inset-top, 0px) + 12px) 16px 0", overflow: "auto", flex: "1 1 auto", minHeight: 0 }}>
        <h1 style={{ margin: "0 0 8px", fontSize: 22 }}>视口诊断</h1>
        <p style={{ margin: "0 0 12px", fontSize: 13, opacity: 0.8 }}>
          点下面的方案，看底部的绿条是否贴着屏幕最底边（红框是这一层的边界）。最后请截一张图发我。
        </p>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
          {(Object.keys(STRATEGIES) as Strategy[]).map((key) => (
            <button key={key} type="button" onClick={() => setStrategy(key)} style={{
              minHeight: 40, padding: "0 12px", borderRadius: 999, border: "1px solid #fff", font: "inherit", fontSize: 13,
              background: key === strategy ? "#fff" : "transparent", color: key === strategy ? "#17143A" : "#fff",
            }}>{STRATEGIES[key].label}</button>
          ))}
        </div>
        <table style={{ fontSize: 13, borderCollapse: "collapse", width: "100%" }}>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label}>
                <td style={{ padding: "3px 8px 3px 0", opacity: 0.75 }}>{row.label}</td>
                <td style={{ padding: "3px 0", fontVariantNumeric: "tabular-nums" }}>{row.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ flex: "0 0 auto", height: 24, background: "#34c759", color: "#000", fontSize: 12, textAlign: "center", lineHeight: "24px" }}>
        底边标记（应贴着屏幕最底部）
      </div>
    </div>
  );

  return (
    <>
      <div ref={probes} />
      {mounted ? createPortal(layer, document.body) : null}
    </>
  );
}
