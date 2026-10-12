import { ImageResponse } from "next/og";

import { buildCover } from "../../../lib/cover/build-cover";
import { coverHeading, seedFromId } from "../../../lib/cover/programme-cover";
import { fetchPublicProgramme } from "../../../lib/public-programme";
import { formatFreq, stationById, stationForProgramme } from "../../../lib/stations";

export const alt = "WaveCast 节目";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const INK = "#1D1D1F";
const INK_2 = "#6E6E73";
const INK_3 = "#8E8E93";

/** Noto Sans SC cut down to the glyphs this card needs (the Google Fonts `text=` subset). */
async function loadFont(text: string, weight: 400 | 700): Promise<ArrayBuffer | null> {
  try {
    const css = await (await fetch(
      `https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@${weight}&text=${encodeURIComponent(text)}`,
      // An old user agent makes Google answer with TrueType, which the renderer can read.
      { headers: { "User-Agent": "Mozilla/5.0 (Macintosh; U; Intel Mac OS X 10_6_8; de-at) AppleWebKit/533.21.1 (KHTML, like Gecko) Version/5.0.5 Safari/533.21.1" } },
    )).text();
    const url = css.match(/src: url\((.+?)\) format\('(?:opentype|truetype)'\)/)?.[1];
    if (!url) return null;
    const response = await fetch(url);
    return response.ok ? await response.arrayBuffer() : null;
  } catch {
    return null;
  }
}

function clamp(text: string, max: number): string {
  const chars = [...text];
  return chars.length > max ? chars.slice(0, max - 1).join("") + "…" : text;
}

export default async function Image({ params }: { params: Promise<{ seedId: string }> }) {
  const { seedId } = await params;
  const programme = await fetchPublicProgramme(seedId);
  const station = programme
    ? (programme.station ? stationById(programme.station) : stationForProgramme(programme.id, programme.title, programme.description))
    : stationById("casual");
  const title = programme ? clamp(programme.title, 28) : "WaveCast";
  const description = programme ? clamp(programme.description, 56) : "";
  const minutes = programme ? Math.max(1, Math.round(programme.estimated_duration_seconds / 60)) : 0;
  const meta = programme ? `FM ${formatFreq(station.freq)} ${station.name} · 约 ${minutes} 分钟` : "";
  const cover = buildCover({
    stationId: station.id,
    seed: seedFromId(programme?.id ?? "wavecast"),
    heading: coverHeading(programme?.title ?? "") ?? "",
    bare: true,
  });

  const text = `${title}${description}${meta}WaveCast wavecast.space`;
  const [regular, bold] = await Promise.all([loadFont(text, 400), loadFont(text, 700)]);
  const fonts = regular && bold
    ? [
      { name: "Noto Sans SC", data: regular, weight: 400 as const, style: "normal" as const },
      { name: "Noto Sans SC", data: bold, weight: 700 as const, style: "normal" as const },
    ]
    : [];
  // Without the font the Chinese would render as empty boxes; show the brand and cover only.
  const withText = fonts.length > 0;

  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", background: "#F2F2F4", color: INK, fontFamily: "Noto Sans SC", position: "relative" }}>
        <div style={{ width: 630, height: 630, display: "flex", background: cover.bg }}>
          <svg width="630" height="630" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
            {cover.slots.map((slot, index) => (
              <path
                key={index}
                d={slot.d}
                fill={slot.fill}
                fillOpacity={slot.o}
                stroke={slot.stroke}
                strokeWidth={slot.sw}
                strokeOpacity={slot.so}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ))}
          </svg>
        </div>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "space-between", padding: "72px 64px 56px 64px" }}>
          {withText && programme ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 26, color: INK_2 }}>
                <div style={{ width: 12, height: 12, borderRadius: 6, background: station.light }} />
                {meta}
              </div>
              <div style={{ display: "flex", fontSize: 60, fontWeight: 700, lineHeight: 1.18 }}>{title}</div>
              <div style={{ display: "flex", fontSize: 28, lineHeight: 1.5, color: INK_2 }}>{description}</div>
            </div>
          ) : <div style={{ display: "flex" }} />}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ display: "flex", fontSize: 30, fontWeight: 700 }}>WaveCast</div>
            <div style={{ display: "flex", fontSize: 24, color: INK_3 }}>wavecast.space</div>
          </div>
        </div>
      </div>
    ),
    { ...size, ...(fonts.length ? { fonts } : {}) },
  );
}
