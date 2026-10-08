"use client";

import { useEffect, useState } from "react";

import { STATUS_BAR_STYLE, type LabVariant } from "../variants";

const BACKGROUNDS = {
  light: { label: "浅色（首页）", css: "linear-gradient(#E0E4F0, #F2F2F4 60%)", color: "#E0E4F0", ink: "#1D1D1F" },
  dark: { label: "深色（播放页）", css: "linear-gradient(#2A241A, #3A2C20)", color: "#2A241A", ink: "#FFFFFF" },
  navy: { label: "深蓝（夜里）", css: "linear-gradient(#17143A, #231E55)", color: "#17143A", ink: "#FFFFFF" },
} as const;
type Background = keyof typeof BACKGROUNDS;

function setThemeColor(color: string | null) {
  let meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (color === null) {
    meta?.remove();
    return;
  }
  if (!meta) {
    meta = document.createElement("meta");
    meta.name = "theme-color";
    document.head.append(meta);
  }
  meta.content = color;
}

/** Temporary: compare status-bar looks on a real iPhone. Nothing here ships. */
export function StatusBarLab({ variant }: { variant: LabVariant }) {
  const [bg, setBg] = useState<Background>("dark");
  const [matchTheme, setMatchTheme] = useState(false);
  const current = BACKGROUNDS[bg];

  useEffect(() => {
    setThemeColor(matchTheme ? current.color : "#F2F2F4");
  }, [matchTheme, current.color]);

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 200, background: current.css, color: current.ink, padding: "calc(env(safe-area-inset-top, 0px) + 24px) 24px 24px", overflow: "auto" }}>
      <h1 style={{ margin: "0 0 4px", fontSize: 26 }}>状态栏实验 {variant === "default" ? "A" : "B"}</h1>
      <p style={{ margin: "0 0 20px", opacity: 0.75, fontSize: 14 }}>
        状态栏样式：{STATUS_BAR_STYLE[variant]}。请用主屏幕图标打开本页，看屏幕最顶端。
      </p>
      <p style={{ margin: "0 0 8px", fontSize: 14 }}>背景</p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 20 }}>
        {(Object.keys(BACKGROUNDS) as Background[]).map((key) => (
          <button key={key} type="button" onClick={() => setBg(key)} style={chip(bg === key, current.ink)}>
            {BACKGROUNDS[key].label}
          </button>
        ))}
      </div>
      <p style={{ margin: "0 0 8px", fontSize: 14 }}>主题色 theme-color</p>
      <div style={{ display: "flex", gap: 8, marginBottom: 24 }}>
        <button type="button" onClick={() => setMatchTheme(false)} style={chip(!matchTheme, current.ink)}>固定浅灰</button>
        <button type="button" onClick={() => setMatchTheme(true)} style={chip(matchTheme, current.ink)}>跟随背景</button>
      </div>
      <p style={{ margin: 0, opacity: 0.75, fontSize: 13, lineHeight: 1.6 }}>
        看三件事：1) 顶部有没有一条突兀的浅色带；2) 时间和电量是否看得清；3) 切换背景和主题色后顶部是否变化。
        另一个变体的入口：/lab/status-bar/{variant === "default" ? "translucent" : "default"}
      </p>
    </div>
  );
}

function chip(active: boolean, ink: string) {
  return {
    minHeight: 44,
    padding: "0 14px",
    borderRadius: 999,
    border: `1px solid ${ink}`,
    background: active ? ink : "transparent",
    color: active ? (ink === "#FFFFFF" ? "#1D1D1F" : "#FFFFFF") : ink,
    font: "inherit",
    fontSize: 14,
  } as const;
}
