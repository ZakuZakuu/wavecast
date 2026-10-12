import type { Metadata } from "next";
import { Suspense } from "react";

import { ProgrammeDetailPage } from "../../../components/programme/programme-detail-page";
import { fetchPublicProgramme } from "../../../lib/public-programme";

type Params = { params: Promise<{ seedId: string }> };

// A shared link unfurls as the programme: its title and one-line promise.
export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { seedId } = await params;
  const programme = await fetchPublicProgramme(seedId);
  if (!programme) return { title: "WaveCast 节目" };
  const description = programme.description;
  return {
    title: `${programme.title} · WaveCast`,
    description,
    openGraph: { title: programme.title, description, siteName: "WaveCast", type: "website" },
    twitter: { card: "summary_large_image", title: programme.title, description },
  };
}

export default async function ProgramDetailRoute({ params }: Params) {
  const { seedId } = await params;
  return (
    <Suspense fallback={null}>
      <ProgrammeDetailPage programmeId={seedId} />
    </Suspense>
  );
}
