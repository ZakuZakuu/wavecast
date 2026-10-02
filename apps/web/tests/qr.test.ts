import qrcode from "qrcode-generator";
import { describe, expect, it } from "vitest";

import { qrPath } from "../lib/qr";

describe("qrPath", () => {
  it("encodes a URL into a square path of dark-module runs", () => {
    const url = "https://wavecast.example/episode/materialized/abc-123";
    const { size, d } = qrPath(url);
    expect(size).toBeGreaterThanOrEqual(21);
    expect((size - 17) % 4).toBe(0);
    expect(d.startsWith("M0 0h7v1h-7z")).toBe(true); // finder pattern top row
  });

  it("covers exactly the dark modules", () => {
    const url = "https://wavecast.example/";
    const { size, d } = qrPath(url);
    const reference = qrcode(0, "M");
    reference.addData(url, "Byte");
    reference.make();
    let dark = 0;
    for (let row = 0; row < size; row += 1) {
      for (let col = 0; col < size; col += 1) if (reference.isDark(row, col)) dark += 1;
    }
    const covered = [...d.matchAll(/h(\d+)v1/g)].reduce((sum, match) => sum + Number(match[1]), 0);
    expect(covered).toBe(dark);
  });

  it("is deterministic", () => {
    expect(qrPath("https://a.example/x")).toEqual(qrPath("https://a.example/x"));
  });
});
