import type { Metadata } from "next";
import { Suspense } from "react";

import { ProgrammeDetailPage } from "../../../components/programme/programme-detail-page";
import { programmeMetadata } from "../../../lib/programme-metadata";
import { fetchPublicProgramme } from "../../../lib/public-programme";

type Params = { params: Promise<{ seedId: string }> };

// A shared link unfurls as the programme: its title and one-line promise.
export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { seedId } = await params;
  return programmeMetadata(await fetchPublicProgramme(seedId));
}

export default async function ProgramDetailRoute({ params }: Params) {
  const { seedId } = await params;
  return (
    <Suspense fallback={null}>
      <ProgrammeDetailPage programmeId={seedId} />
    </Suspense>
  );
}
