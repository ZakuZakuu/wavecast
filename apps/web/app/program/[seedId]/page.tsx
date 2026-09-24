import { ProgramDetail } from "../../../components/program-detail";

export default async function ProgramDetailPage({
  params,
}: {
  params: Promise<{ seedId: string }>;
}) {
  const { seedId } = await params;
  return <ProgramDetail seedId={seedId} />;
}
