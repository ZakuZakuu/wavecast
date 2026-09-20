import { EpisodePlayer } from "../../../../components/episode-player";

export default async function MaterializedEpisodePage({
  params,
}: {
  params: Promise<{ episodeId: string }>;
}) {
  const { episodeId } = await params;
  return <EpisodePlayer episodeId={episodeId} />;
}
