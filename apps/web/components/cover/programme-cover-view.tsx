import { programmeCover } from "../../lib/cover/programme-cover";
import type { StationId } from "../../lib/stations";
import { TypeCover } from "./type-cover";

/** Cover for a programme id/title/station; `bare` forces the no-text version. */
export function ProgrammeCoverView({
  id,
  title,
  stationId,
  bare = false,
  radius = 12,
  className,
}: {
  id: string;
  title: string;
  stationId: StationId;
  bare?: boolean;
  radius?: number;
  className?: string;
}) {
  const { params } = programmeCover({ id, title, stationId });
  return <TypeCover params={bare ? { ...params, bare: true } : params} radius={radius} className={className} />;
}
