import { redirect } from "next/navigation";

// Programme detail pages were removed in UI P0: opening a programme plays it.
export default async function ProgramDetailPage({
  params,
}: {
  params: Promise<{ seedId: string }>;
}) {
  const { seedId } = await params;
  redirect(`/episode/${encodeURIComponent(seedId)}`);
}
