import { notFound } from "next/navigation";

import { isLabVariant } from "../../variants";

/** Temporary: one installable manifest per status-bar variant. */
export const dynamicParams = false;

export async function GET(_request: Request, { params }: { params: Promise<{ variant: string }> }) {
  const { variant } = await params;
  if (!isLabVariant(variant)) notFound();
  return Response.json(
    {
      id: `/lab/status-bar/${variant}`,
      name: `状态栏实验 · ${variant}`,
      short_name: variant === "default" ? "状态栏A" : "状态栏B",
      start_url: `/lab/status-bar/${variant}`,
      scope: `/lab/status-bar/${variant}`,
      display: "standalone",
      orientation: "portrait",
      background_color: "#F2F2F4",
      theme_color: "#F2F2F4",
      icons: [
        { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
        { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      ],
    },
    { headers: { "Content-Type": "application/manifest+json" } },
  );
}
