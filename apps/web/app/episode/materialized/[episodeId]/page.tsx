import { PlayerScreen } from "../../../../components/player/player-screen";

export default async function MaterializedEpisodePage({
  params,
}: {
  params: Promise<{ episodeId: string }>;
}) {
  const { episodeId } = await params;
  return <PlayerScreen episodeId={episodeId} />;
}
