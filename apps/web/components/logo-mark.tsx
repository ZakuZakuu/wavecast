import { logoMarkSvg } from "../lib/brand/logo-mark";

export function LogoMark({ size = 64, dark = false }: { size?: number; dark?: boolean }) {
  return (
    <span
      aria-hidden="true"
      style={{ display: "inline-block", width: size, height: size, lineHeight: 0 }}
      dangerouslySetInnerHTML={{ __html: logoMarkSvg({ dark }).replace("<svg ", `<svg width="${size}" height="${size}" `) }}
    />
  );
}
