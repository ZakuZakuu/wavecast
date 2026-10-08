/** Temporary: installable manifest for the viewport diagnostics page. */
export function GET() {
  return Response.json(
    {
      id: "/lab/viewport",
      name: "视口诊断",
      short_name: "视口诊断",
      start_url: "/lab/viewport",
      scope: "/lab/viewport",
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
