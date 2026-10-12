import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { programmeMetadata } from "../../../lib/programme-metadata";
import { fetchPublicProgramme, resolveShortCode } from "../../../lib/public-programme";

type Props = {
  params: Promise<{ code: string }>;
  searchParams: Promise<{ c?: string | string[] }>;
};

// The page itself only redirects, but the chat apps that unfurl the link read this first, and
// many do not follow a redirect that arrives after the page has started streaming.
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { code } = await params;
  const id = await resolveShortCode(code);
  if (!id) return programmeMetadata(null);
  return programmeMetadata(await fetchPublicProgramme(id), `/program/${encodeURIComponent(id)}/opengraph-image`);
}

/** Short link: /p/<code> goes to the programme's own page, keeping the cover hint. */
export default async function ShortLink({ params, searchParams }: Props) {
  const { code } = await params;
  const { c } = await searchParams;
  const id = await resolveShortCode(code);
  const cover = Array.isArray(c) ? c[0] : c;
  const query = cover ? `?c=${encodeURIComponent(cover)}` : "";
  // An unknown code lands on the programme page's own "找不到了" screen.
  redirect(`/program/${encodeURIComponent(id ?? code)}${query}`);
}
