import type { Metadata } from "next";

import type { PublicProgramme } from "./types";

/** The title and one-line promise a shared link unfurls as. */
export function programmeMetadata(programme: PublicProgramme | null, imagePath?: string): Metadata {
  if (!programme) return { title: "WaveCast 节目" };
  const description = programme.description;
  const images = imagePath ? [{ url: imagePath, width: 1200, height: 630, alt: programme.title }] : undefined;
  return {
    title: `${programme.title} · WaveCast`,
    description,
    openGraph: { title: programme.title, description, siteName: "WaveCast", type: "website", ...(images ? { images } : {}) },
    twitter: { card: "summary_large_image", title: programme.title, description, ...(images ? { images: images.map((image) => image.url) } : {}) },
  };
}
