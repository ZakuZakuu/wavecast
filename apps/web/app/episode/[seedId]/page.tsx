import { PlayerScreen } from "../../../components/player/player-screen";

export default async function EpisodePage({ params }: { params: Promise<{ seedId: string }> }) {
  const { seedId } = await params;
  return <PlayerScreen seedId={seedId} />;
}
