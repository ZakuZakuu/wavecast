// Rasterises a bare cover to a 512px PNG object URL for MediaSession artwork.
import { bareCoverSvg, type CoverParams } from "./build-cover";

export async function coverArtworkUrl(params: CoverParams, size = 512): Promise<string | null> {
  if (typeof document === "undefined") return null;
  const svg = bareCoverSvg(params, size);
  const source = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
  const image = new Image(size, size);
  image.decoding = "async";
  const loaded = new Promise<void>((resolve, reject) => {
    image.onload = () => resolve();
    image.onerror = () => reject(new Error("cover image failed"));
  });
  image.src = source;
  try {
    await loaded;
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const context = canvas.getContext("2d");
    if (!context) return null;
    context.drawImage(image, 0, 0, size, size);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    return blob ? URL.createObjectURL(blob) : null;
  } catch {
    return null;
  }
}
