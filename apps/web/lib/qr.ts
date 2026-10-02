// QR code for the desktop side card, drawn as one SVG path (no canvas, no images).
import qrcode from "qrcode-generator";

export type QrPath = { size: number; d: string };

/** Dark modules as a single path in module units; `size` excludes the quiet zone. */
export function qrPath(text: string): QrPath {
  const code = qrcode(0, "M");
  code.addData(text, "Byte");
  code.make();
  const size = code.getModuleCount();
  let d = "";
  for (let row = 0; row < size; row += 1) {
    let col = 0;
    while (col < size) {
      if (!code.isDark(row, col)) {
        col += 1;
        continue;
      }
      const start = col;
      while (col < size && code.isDark(row, col)) col += 1;
      // Horizontal runs keep the path short.
      d += `M${start} ${row}h${col - start}v1h${start - col}z`;
    }
  }
  return { size, d };
}
