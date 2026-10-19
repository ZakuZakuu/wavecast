import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { programmeMetadata } from "../../../lib/programme-metadata";
import { NotFound } from "../../../components/programme/programme-detail-page";
import { fetchPublicProgramme, resolveShortCode, resolveShortLink } from "../../../lib/public-programme";

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

/** Short link: /p/<code> goes to the published programme's own page, keeping the cover hint. */
export default async function ShortLink({ params, searchParams }: Props) {
  const { code } = await params;
  const { c } = await searchParams;
  const link = await resolveShortLink(code);
  // A link of the old kind, or one that never existed, says so here instead of opening a copy.
  if ("gone" in link) return <NotFound kind={link.gone} />;
  const cover = Array.isArray(c) ? c[0] : c;
  const query = cover ? `?c=${encodeURIComponent(cover)}` : "";
  redirect(`/program/${encodeURIComponent(link.id)}${query}`);
}
