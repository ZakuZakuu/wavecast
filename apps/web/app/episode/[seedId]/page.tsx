import { EpisodePlayer } from "../../../components/episode-player";

export default async function EpisodePage({ params }: { params: Promise<{ seedId: string }> }) {
  const { seedId } = await params;
  return <EpisodePlayer seedId={seedId} />;
}
